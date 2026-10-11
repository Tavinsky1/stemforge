# Stemforge Remote Script
# Runs INSIDE Ableton Live as its own Control Surface, side by side with any other script (it is NOT AbletonMCP and
# never touches that folder). Listens on 127.0.0.1:9878 for JSON {"type", "params"} commands from the Stemforge app.
#
# Deliberately small and unable to destroy anything:
#   * no delete of tracks, clips or scenes
#   * no device loading, no parameter setting, no mixer/transport control, no launching
#   * it only ever WRITES to tracks and scenes that this script itself created in this Live session
#     (writes to anything else are refused); reads of any track are allowed
#   * it never overwrites a clip or an arrangement clip
# set_tempo is the one set-wide change, and the Stemforge app only sends it when the user ticks the box.

from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import hashlib
import json
import socket
import threading
import time
import traceback

try:
    import Queue as queue   # Python 2
except ImportError:
    import queue            # Python 3

SCRIPT_NAME = "Stemforge"
# Bump when behaviour changes. list_commands reports this plus a hash of the file Live actually loaded.
SCRIPT_VERSION = "stemforge-script-2"
DEFAULT_PORT = 9878
HOST = "127.0.0.1"
STATUS_FILE = "/tmp/stemforge_status.json"
COMMAND_TIMEOUT = 10.0


def create_instance(c_instance):
    """Called by Ableton to instantiate this control surface."""
    return Stemforge(c_instance)


def _hash_own_source():
    try:
        with open(__file__, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except Exception:
        return None


_SOURCE_SHA256 = _hash_own_source()

# Every command the dispatcher accepts. tests/test_stemforge_script.py keeps this honest.
COMMAND_NAMES = (
    "add_notes_to_arrangement_clip", "add_notes_to_clip", "claim_scene", "create_arrangement_clip",
    "create_clip", "create_midi_track", "create_scene_with_name",
    "get_arrangement_clip_notes", "get_clip_notes", "get_session_info",
    "list_commands", "set_clip_name", "set_tempo", "set_track_name",
)


def _key(obj):
    """Identity of a Live object that survives Live handing out a fresh wrapper each time."""
    ptr = getattr(obj, "_live_ptr", None)
    return ptr if ptr is not None else id(obj)


class Stemforge(ControlSurface):
    """TCP command gateway for the Stemforge app."""

    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        self._song = self.song()
        self._created_tracks = []     # Live track objects this script created (the only tracks it may write to)
        self._created_scenes = []     # same for scenes
        self._handlers = {
            "list_commands": self._list_commands,
            "get_session_info": self._get_session_info,
            "set_tempo": self._set_tempo,
            "create_midi_track": self._create_midi_track,
            "set_track_name": self._set_track_name,
            "create_scene_with_name": self._create_scene_with_name,
            "claim_scene": self._claim_scene,
            "create_clip": self._create_clip,
            "set_clip_name": self._set_clip_name,
            "add_notes_to_clip": self._add_notes_to_clip,
            "get_clip_notes": self._get_clip_notes,
            "create_arrangement_clip": self._create_arrangement_clip,
            "add_notes_to_arrangement_clip": self._add_notes_to_arrangement_clip,
            "get_arrangement_clip_notes": self._get_arrangement_clip_notes,
        }
        self.log_message("Stemforge %s starting" % SCRIPT_VERSION)
        self.start_server()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def disconnect(self):
        self.running = False
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
        ControlSurface.disconnect(self)
        self._write_status("disconnected")

    def _write_status(self, status, extra=None):
        payload = {"status": status, "port": DEFAULT_PORT, "version": SCRIPT_VERSION, "timestamp": time.time()}
        if extra:
            payload.update(extra)
        try:
            with open(STATUS_FILE, "w") as fh:
                json.dump(payload, fh)
        except Exception:
            pass

    # ── Socket server ────────────────────────────────────────────────────────

    def start_server(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            self._write_status("listening")
            self.log_message("Stemforge listening on port %d" % DEFAULT_PORT)
            self.show_message("Stemforge: ready on port %d" % DEFAULT_PORT)
        except Exception as e:
            self.log_message("Stemforge could not start its server: %s" % str(e))
            self._write_status("error", {"error": str(e)})
            self.show_message("Stemforge: port %d is busy or unavailable (%s)" % (DEFAULT_PORT, str(e)))

    def _server_thread(self):
        try:
            self.server.settimeout(1.0)
            while self.running:
                try:
                    client, _address = self.server.accept()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log_message("Accept error: %s" % str(e))
                    time.sleep(0.5)
                    continue
                t = threading.Thread(target=self._handle_client, args=(client,))
                t.daemon = True
                t.start()
                self.client_threads = [x for x in self.client_threads if x.is_alive()] + [t]
        except Exception as e:
            self.log_message("Server thread error: %s" % str(e))

    def _handle_client(self, client):
        client.settimeout(None)
        buffer = ""
        try:
            while self.running:
                data = client.recv(65536)
                if not data:
                    break
                try:
                    buffer += data.decode("utf-8")
                except AttributeError:
                    buffer += data   # Python 2
                try:
                    command = json.loads(buffer)
                except ValueError:
                    continue         # incomplete JSON: keep reading
                buffer = ""
                response = self._process_command(command)
                payload = json.dumps(response)
                try:
                    client.sendall(payload.encode("utf-8"))
                except AttributeError:
                    client.sendall(payload)
        except Exception as e:
            self.log_message("Client error: %s" % str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _process_command(self, command):
        """Run one command on Live's main thread and return the JSON-able response."""
        command_type = command.get("type", "")
        params = command.get("params", {}) or {}
        self.log_message("Command: %s" % command_type)
        response_queue = queue.Queue()

        def main_thread_task():
            try:
                response_queue.put({"status": "success", "result": self.execute(command_type, params)})
            except Exception as exc:
                self.log_message("Command %s failed: %s" % (command_type, str(exc)))
                response_queue.put({"status": "error", "message": str(exc)})

        try:
            self.schedule_message(0, main_thread_task)
        except AssertionError:
            main_thread_task()       # already on the main thread
        try:
            return response_queue.get(timeout=COMMAND_TIMEOUT)
        except queue.Empty:
            return {"status": "error", "message": "Timeout waiting for Ableton to run '%s'" % command_type}

    def execute(self, command_type, params):
        """Dispatch one command. Unknown commands (including anything destructive) are refused."""
        handler = self._handlers.get(command_type)
        if handler is None:
            raise ValueError("Unknown command: %s" % command_type)
        return handler(params)

    # ── Ownership: this script only writes to what it created ────────────────

    def _is_created(self, obj, created):
        k = _key(obj)
        return any(k == _key(c) or obj == c for c in created)

    def _track(self, params):
        index = int(params.get("track_index", -1))
        if index < 0 or index >= len(self._song.tracks):
            raise IndexError("Track index %d out of range" % index)
        return index, self._song.tracks[index]

    def _owned_track(self, params):
        index, track = self._track(params)
        if not self._is_created(track, self._created_tracks):
            raise PermissionError(
                "Track %d ('%s') was not created by Stemforge in this session, so Stemforge will not write to it"
                % (index, track.name))
        return index, track

    def _owned_slot(self, params):
        """The clip slot for (track_index, clip_index): both the track and the scene row must be Stemforge's own."""
        index, track = self._owned_track(params)
        clip_index = int(params.get("clip_index", -1))
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index %d out of range" % clip_index)
        scene = self._song.scenes[clip_index]
        if not self._is_created(scene, self._created_scenes):
            raise PermissionError(
                "Scene %d ('%s') was not created by Stemforge, so Stemforge will not put clips in its row"
                % (clip_index, scene.name))
        return track.clip_slots[clip_index]

    # ── Commands ─────────────────────────────────────────────────────────────

    def _list_commands(self, params):
        return {
            "script": SCRIPT_NAME,
            "version": SCRIPT_VERSION,
            "source_sha256": _SOURCE_SHA256,
            "file": __file__,
            "port": DEFAULT_PORT,
            "can_delete": False,
            "commands": sorted(COMMAND_NAMES),
        }

    def _get_session_info(self, params):
        tracks = []
        for i, t in enumerate(self._song.tracks):
            tracks.append({"index": i, "name": t.name, "is_midi_track": bool(t.has_midi_input),
                           "created_by_stemforge": self._is_created(t, self._created_tracks)})
        return {
            "tempo": self._song.tempo,
            "signature_numerator": self._song.signature_numerator,
            "signature_denominator": self._song.signature_denominator,
            "track_count": len(self._song.tracks),
            "scene_count": len(self._song.scenes),
            "tracks": tracks,
        }

    def _set_tempo(self, params):
        tempo = float(params.get("tempo", 0))
        if tempo < 20.0 or tempo > 999.0:
            raise ValueError("Tempo %.2f is outside Live's 20-999 BPM range" % tempo)
        self._song.tempo = tempo
        return {"tempo": self._song.tempo}

    def _create_midi_track(self, params):
        self._song.create_midi_track(-1)          # always appended at the end; never inserted among yours
        index = len(self._song.tracks) - 1
        track = self._song.tracks[index]
        self._created_tracks.append(track)
        return {"index": index, "name": track.name}

    def _set_track_name(self, params):
        index, track = self._owned_track(params)
        track.name = str(params.get("name", ""))
        return {"index": index, "name": track.name}

    def _create_scene_with_name(self, params):
        name = str(params.get("name", "Section"))
        self._song.create_scene(len(self._song.scenes))   # appended at the end
        index = len(self._song.scenes) - 1
        scene = self._song.scenes[index]
        self._created_scenes.append(scene)
        scene.name = name
        if scene.name != name:
            raise ValueError("Scene name not applied: wanted %r, Live has %r" % (name, scene.name))
        return {"scene_index": index, "name": scene.name}

    def _claim_scene(self, params):
        """Take over an EXISTING scene row so a build can start at scene 1. Only a row that is completely empty is
        taken: no clip on any track, no name (or just a number), no tempo / time-signature override. Anything else is
        refused and left exactly as it is. The row is then Stemforge's own and gets the section name."""
        index = int(params.get("scene_index", -1))
        if index < 0 or index >= len(self._song.scenes):
            raise IndexError("Scene index %d out of range" % index)
        scene = self._song.scenes[index]
        if self._is_created(scene, self._created_scenes):
            raise ValueError("Scene %d is already Stemforge's" % index)
        current = str(scene.name or "").strip()
        if current and not current.isdigit():
            raise PermissionError("Scene %d is named %r, so Stemforge leaves it alone" % (index, current))
        if getattr(scene, "tempo_enabled", False) or getattr(scene, "time_signature_enabled", False):
            raise PermissionError("Scene %d has its own tempo or time signature, so Stemforge leaves it alone" % index)
        for t_index, t in enumerate(self._song.tracks):
            if index < len(t.clip_slots) and t.clip_slots[index].has_clip:
                raise PermissionError("Scene %d already holds a clip on track %d ('%s'), so Stemforge leaves it alone"
                                      % (index, t_index, t.name))
        name = str(params.get("name", "Section"))
        scene.name = name
        if scene.name != name:
            raise ValueError("Scene name not applied: wanted %r, Live has %r" % (name, scene.name))
        self._created_scenes.append(scene)
        return {"scene_index": index, "name": scene.name, "claimed": True}

    def _create_clip(self, params):
        slot = self._owned_slot(params)
        if slot.has_clip:
            raise ValueError("That clip slot already holds a clip; Stemforge never overwrites clips")
        slot.create_clip(float(params.get("length", 4.0)))
        return {"name": slot.clip.name, "length": float(slot.clip.length)}

    def _set_clip_name(self, params):
        slot = self._owned_slot(params)
        if not slot.has_clip:
            raise ValueError("No clip in that slot")
        slot.clip.name = str(params.get("name", ""))
        return {"name": slot.clip.name}

    def _append_notes(self, clip, notes):
        """Append notes (never replaces). Live 12 add_new_notes takes MidiNoteSpecification objects.
        There is deliberately no fallback to the old replace-all note API: it would silently drop notes."""
        import Live
        if not hasattr(clip, "add_new_notes") or not hasattr(Live.Clip, "MidiNoteSpecification"):
            raise RuntimeError("add_new_notes/MidiNoteSpecification not available (needs Live 11 or newer)")
        specs = tuple(
            Live.Clip.MidiNoteSpecification(
                pitch=int(n.get("pitch", 60)),
                start_time=float(n.get("start_time", 0.0)),
                duration=float(n.get("duration", 0.25)),
                velocity=float(n.get("velocity", 100)),
                mute=bool(n.get("mute", False)),
            )
            for n in notes
        )
        if specs:
            clip.add_new_notes(specs)
        return len(specs)

    def _add_notes_to_clip(self, params):
        slot = self._owned_slot(params)
        if not slot.has_clip:
            raise ValueError("No clip in that slot")
        return {"note_count": self._append_notes(slot.clip, params.get("notes", []))}

    @staticmethod
    def _read_notes(clip):
        raw = clip.get_notes_extended(from_pitch=int(0), pitch_span=int(128),
                                      from_time=float(0.0), time_span=float(clip.length))
        return [{"pitch": int(n.pitch), "start_time": float(n.start_time), "duration": float(n.duration),
                 "velocity": int(n.velocity), "mute": bool(n.mute)} for n in raw]

    def _get_clip_notes(self, params):
        index, track = self._track(params)
        clip_index = int(params.get("clip_index", -1))
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index %d out of range" % clip_index)
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            return {"notes": [], "note_count": 0}
        notes = self._read_notes(slot.clip)
        return {"notes": notes, "note_count": len(notes), "clip_length": float(slot.clip.length)}

    def _find_arrangement_clip(self, track, start_time):
        for clip in track.arrangement_clips:
            if abs(clip.start_time - float(start_time)) < 1e-6:
                return clip
        raise ValueError("No arrangement clip at beat %.3f on that track" % float(start_time))

    def _create_arrangement_clip(self, params):
        index, track = self._owned_track(params)
        if not track.has_midi_input:
            raise ValueError("Track %d is not a MIDI track" % index)
        if not hasattr(track, "create_midi_clip"):
            raise RuntimeError("Track.create_midi_clip is not available in this Live version")
        start_time = float(params.get("start_time", 0.0))
        length = float(params.get("length", 4.0))
        if start_time < 0.0 or length <= 0.0:
            raise ValueError("start_time must be >= 0 and length > 0")
        end_time = start_time + length
        for existing in track.arrangement_clips:
            if existing.start_time < end_time and existing.end_time > start_time:
                raise ValueError("Arrangement range %.3f-%.3f overlaps the clip '%s'; Stemforge never overwrites clips"
                                 % (start_time, end_time, existing.name))
        track.create_midi_clip(start_time, length)
        clip = self._find_arrangement_clip(track, start_time)      # don't rely on the return value
        name = str(params.get("name", ""))
        if name:
            clip.name = name
        notes = params.get("notes", [])
        written = self._append_notes(clip, notes) if notes else 0
        return {"track_index": index, "name": clip.name, "start_time": float(clip.start_time),
                "end_time": float(clip.end_time), "length": float(clip.length), "notes_sent": written}

    def _add_notes_to_arrangement_clip(self, params):
        index, track = self._owned_track(params)
        clip = self._find_arrangement_clip(track, params.get("start_time", 0.0))
        return {"note_count": self._append_notes(clip, params.get("notes", []))}

    def _get_arrangement_clip_notes(self, params):
        index, track = self._track(params)
        clip = self._find_arrangement_clip(track, params.get("start_time", 0.0))
        notes = self._read_notes(clip)
        return {"notes": notes, "note_count": len(notes), "clip_length": float(clip.length)}
