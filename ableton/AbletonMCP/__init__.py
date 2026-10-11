# AbletonMCP Remote Script
# Runs INSIDE Ableton Live as a MIDI Control Surface.
# Listens on localhost:9877 for JSON commands from the MCP server.
#
# Source: adapted from ahujasid/ableton-mcp (MIT licence)
# Port: 9877  ← NOTE: guides that say 9000 are incorrect.

from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback
import os
import hashlib

try:
    import Queue as queue   # Python 2
except ImportError:
    import queue            # Python 3

DEFAULT_PORT = 9877
HOST = "localhost"
STATUS_FILE = "/tmp/ableton_mcp_status.json"

# Bump when behaviour changes. list_commands returns this plus a hash of the
# source file Live actually loaded, so a stale installed copy is detectable.
SCRIPT_VERSION = "stemforge-2"


def _hash_own_source():
    """SHA-256 of this file as loaded (computed once, at import)."""
    try:
        with open(__file__, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except Exception:
        return None


_SOURCE_SHA256 = _hash_own_source()

# Every command _process_command dispatches. Keep in sync with the dispatcher;
# tests/test_remote_script_commands.py fails if they drift.
COMMAND_NAMES = (
    "add_notes_to_arrangement_clip", "add_notes_to_clip",
    "create_arrangement_clip", "create_audio_track",
    "create_clip", "create_midi_track", "create_scene",
    "create_scene_with_name", "delete_clip", "delete_track",
    "duplicate_clip_to_scene", "fire_clip", "fire_scene",
    "get_arrangement_clip_notes",
    "get_browser_item", "get_browser_items_at_path", "get_browser_tree",
    "get_clip_notes", "get_drum_rack_pads", "get_session_grid",
    "get_session_info", "get_session_scenes", "get_track_info",
    "list_commands", "load_browser_item", "load_device_by_name",
    "load_instrument_or_effect", "mute_track", "replace_notes_in_clip",
    "set_clip_name", "set_device_parameter", "set_scene_name",
    "set_send_level", "set_tempo", "set_track_arm", "set_track_name",
    "set_track_volume", "start_playback", "stop_clip", "stop_playback",
)


def create_instance(c_instance):
    """Called by Ableton to instantiate this control surface."""
    return AbletonMCP(c_instance)


class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script — TCP command gateway for the MCP server."""

    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP initializing…")

        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        self._song = self.song()

        self._write_status("starting")

        self.start_server()
        self.log_message("AbletonMCP ready on port %d" % DEFAULT_PORT)
        self.show_message("AbletonMCP: listening on port %d" % DEFAULT_PORT)
        self._write_status("ready")

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def disconnect(self):
        self.log_message("AbletonMCP disconnecting…")
        self.running = False
        self._write_status("disconnecting")
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
        ControlSurface.disconnect(self)
        self._write_status("disconnected")
        self.log_message("AbletonMCP disconnected")

    def _write_status(self, status, extra=None):
        payload = {
            "status": status,
            "port": DEFAULT_PORT,
            "host": HOST,
            "timestamp": time.time(),
        }
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
            self._write_status("listening")
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            self.log_message("Server started on port %d" % DEFAULT_PORT)
        except Exception as e:
            self.log_message("Error starting server: %s" % str(e))
            self._write_status("error", {"error": str(e)})
            self.show_message("AbletonMCP: Error starting server — %s" % str(e))

    def _server_thread(self):
        try:
            self.server.settimeout(1.0)
            while self.running:
                try:
                    client, address = self.server.accept()
                    self.log_message("Connection from %s" % str(address))
                    self.show_message("AbletonMCP: client connected")
                    self._write_status("client_connected", {"client": str(address)})
                    t = threading.Thread(target=self._handle_client, args=(client,))
                    t.daemon = True
                    t.start()
                    self.client_threads.append(t)
                    self.client_threads = [x for x in self.client_threads if x.is_alive()]
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log_message("Accept error: %s" % str(e))
                    time.sleep(0.5)
        except Exception as e:
            self.log_message("Server thread error: %s" % str(e))

    def _handle_client(self, client):
        client.settimeout(None)
        buffer = ""
        try:
            while self.running:
                data = client.recv(8192)
                if not data:
                    self.log_message("Client disconnected")
                    break
                try:
                    buffer += data.decode("utf-8")
                except AttributeError:
                    buffer += data   # Python 2

                try:
                    command = json.loads(buffer)
                    buffer = ""
                    self.log_message("Command: %s" % command.get("type", "?"))
                    response = self._process_command(command)
                    payload = json.dumps(response)
                    try:
                        client.sendall(payload.encode("utf-8"))
                    except AttributeError:
                        client.sendall(payload)   # Python 2
                except ValueError:
                    continue   # incomplete JSON, keep reading
                except Exception as e:
                    self.log_message("Handler error: %s" % str(e))
                    self.log_message(traceback.format_exc())
                    err = json.dumps({"status": "error", "message": str(e)})
                    try:
                        client.sendall(err.encode("utf-8"))
                    except Exception:
                        break
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Client thread error: %s" % str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass

    # ── Command Dispatcher ───────────────────────────────────────────────────

    def _process_command(self, command):
        command_type = command.get("type", "")
        params = command.get("params", {})
        response = {"status": "success", "result": {}}

        try:
            if True:
                response_queue = queue.Queue()

                def main_thread_task():
                    try:
                        result = None
                        if command_type == "get_session_info":
                            result = self._get_session_info()
                        elif command_type == "get_track_info":
                            result = self._get_track_info(params.get("track_index", 0))
                        elif command_type == "get_clip_notes":
                            result = self._get_clip_notes(
                                params.get("track_index", 0),
                                params.get("clip_index", 0))
                        elif command_type == "get_drum_rack_pads":
                            result = self._get_drum_rack_pads(
                                params.get("track_index", 0))
                        elif command_type == "get_session_scenes":
                            result = self._get_session_scenes()
                        elif command_type == "get_session_grid":
                            result = self._get_session_grid()
                        elif command_type == "get_browser_tree":
                            result = self.get_browser_tree(params.get("category_type", "all"))
                        elif command_type == "get_browser_items_at_path":
                            result = self.get_browser_items_at_path(params.get("path", ""))
                        elif command_type == "get_browser_item":
                            result = self._get_browser_item(
                                params.get("uri"), params.get("path"))
                        elif command_type == "create_midi_track":
                            result = self._create_midi_track(params.get("index", -1))
                        elif command_type == "create_audio_track":
                            result = self._create_audio_track(params.get("index", -1))
                        elif command_type == "set_track_name":
                            result = self._set_track_name(
                                params.get("track_index", 0), params.get("name", ""))
                        elif command_type == "delete_track":
                            result = self._delete_track(params.get("track_index", 0))
                        elif command_type == "create_clip":
                            result = self._create_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("length", 4.0))
                        elif command_type == "add_notes_to_clip":
                            result = self._add_notes_to_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("notes", []))
                        elif command_type == "replace_notes_in_clip":
                            result = self._replace_notes_in_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("notes", []))
                        elif command_type == "delete_clip":
                            result = self._delete_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0))
                        elif command_type == "set_clip_name":
                            result = self._set_clip_name(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("name", ""))
                        elif command_type == "set_tempo":
                            result = self._set_tempo(params.get("tempo", 120.0))
                        elif command_type == "fire_clip":
                            result = self._fire_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0))
                        elif command_type == "stop_clip":
                            result = self._stop_clip(
                                params.get("track_index", 0),
                                params.get("clip_index", 0))
                        elif command_type == "start_playback":
                            result = self._start_playback()
                        elif command_type == "stop_playback":
                            result = self._stop_playback()
                        elif command_type in ("load_instrument_or_effect", "load_browser_item"):
                            result = self._load_browser_item(
                                params.get("track_index", 0),
                                params.get("item_uri") or params.get("uri", ""))
                        elif command_type == "load_device_by_name":
                            result = self._load_device_by_name(
                                params.get("track_index", 0),
                                params.get("name", ""))
                        elif command_type == "set_track_volume":
                            result = self._set_track_volume(
                                params.get("track_index", 0),
                                params.get("volume", 0.85))
                        elif command_type == "set_send_level":
                            result = self._set_send_level(
                                params.get("track_index", 0),
                                params.get("send_index", 0),
                                params.get("value", 0.0))
                        elif command_type == "mute_track":
                            result = self._mute_track(
                                params.get("track_index", 0),
                                bool(params.get("muted", True)))

                        elif command_type == "set_track_arm":
                            result = self._set_track_arm(
                                params.get("track_index", 0),
                                bool(params.get("arm", False)))
                        elif command_type == "set_device_parameter":
                            result = self._set_device_parameter(
                                params.get("track_type", "track"),
                                params.get("track_index", 0),
                                params.get("device_name", ""),
                                params.get("parameter_name", ""),
                                params.get("value", 0.0))
                        elif command_type == "create_scene":
                            result = self._create_scene(params.get("index", -1))
                        elif command_type == "fire_scene":
                            result = self._fire_scene(params.get("scene_index", 0))
                        elif command_type == "set_scene_name":
                            result = self._set_scene_name(
                                params.get("scene_index", 0),
                                params.get("name", ""))
                        elif command_type == "create_scene_with_name":
                            result = self._create_scene_with_name(
                                params.get("name", "Section"))
                        elif command_type == "get_session_grid":
                            result = self._get_session_grid()
                        elif command_type == "duplicate_clip_to_scene":
                            result = self._duplicate_clip_to_scene(
                                params.get("src_track_index", 0),
                                params.get("src_clip_index", 0),
                                params.get("dst_scene_index", 0))
                        elif command_type == "list_commands":
                            result = self._list_commands()
                        elif command_type == "add_notes_to_arrangement_clip":
                            result = self._add_notes_to_arrangement_clip(
                                params.get("track_index", 0),
                                params.get("start_time", 0.0),
                                params.get("notes", []))
                        elif command_type == "get_arrangement_clip_notes":
                            result = self._get_arrangement_clip_notes(
                                params.get("track_index", 0),
                                params.get("start_time", 0.0))
                        elif command_type == "create_arrangement_clip":
                            result = self._create_arrangement_clip(
                                params.get("track_index", 0),
                                params.get("start_time", 0.0),
                                params.get("length", 4.0),
                                params.get("name", ""),
                                params.get("notes", []))
                        else:
                            raise ValueError("Unknown command: %s" % command_type)
                        response_queue.put({"status": "success", "result": result})
                    except Exception as exc:
                        self.log_message("Main thread task error: %s" % str(exc))
                        response_queue.put({"status": "error", "message": str(exc)})

                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    main_thread_task()   # Already on main thread

                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for Ableton operation"

            else:
                response["status"] = "error"
                response["message"] = "Unknown command: %s" % command_type

        except Exception as e:
            self.log_message("Error processing command: %s" % str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)

        return response

    # ── Command Implementations ───────────────────────────────────────────────

    def _get_session_info(self):
        return {
            "tempo": self._song.tempo,
            "signature_numerator": self._song.signature_numerator,
            "signature_denominator": self._song.signature_denominator,
            "track_count": len(self._song.tracks),
            "scene_count": len(self._song.scenes),
            "return_track_count": len(self._song.return_tracks),
            "master_track": {
                "name": "Master",
                "volume": self._song.master_track.mixer_device.volume.value,
                "panning": self._song.master_track.mixer_device.panning.value,
            },
            # tracks list enables name→index resolution in the server layer
            "tracks": [
                {
                    "index": i,
                    "name": t.name,
                    "is_audio_track": t.has_audio_input,
                    "is_midi_track": t.has_midi_input,
                    "mute": t.mute,
                    "devices": [{"name": d.name} for d in t.devices],
                    "clip_slots": [
                        {"index": si, "has_clip": cs.has_clip}
                        for si, cs in enumerate(t.clip_slots)
                    ],
                }
                for i, t in enumerate(self._song.tracks)
            ],
        }

    def _get_track_info(self, track_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index %d out of range" % track_index)
        track = self._song.tracks[track_index]

        clip_slots = []
        for idx, slot in enumerate(track.clip_slots):
            clip_info = None
            if slot.has_clip:
                c = slot.clip
                clip_info = {
                    "name": c.name,
                    "length": c.length,
                    "is_playing": c.is_playing,
                    "is_recording": c.is_recording,
                }
            clip_slots.append({"index": idx, "has_clip": slot.has_clip, "clip": clip_info})

        devices = []
        for didx, dev in enumerate(track.devices):
            devices.append({
                "index": didx,
                "name": dev.name,
                "class_name": dev.class_name,
                "type": self._get_device_type(dev),
            })

        # Audio / return tracks raise on .arm — never let that kill the call.
        arm = False
        try:
            arm = bool(track.arm)
        except Exception:
            arm = False

        return {
            "index": track_index,
            "name": track.name,
            "is_audio_track": track.has_audio_input,
            "is_midi_track": track.has_midi_input,
            "mute": track.mute,
            "solo": track.solo,
            "arm": arm,
            "volume": track.mixer_device.volume.value,
            "panning": track.mixer_device.panning.value,
            "clip_slots": clip_slots,
            "devices": devices,
        }

    def _create_midi_track(self, index):
        self._song.create_midi_track(index)
        new_index = len(self._song.tracks) - 1 if index == -1 else index
        track = self._song.tracks[new_index]
        return {"index": new_index, "name": track.name}

    def _create_audio_track(self, index):
        self._song.create_audio_track(index)
        new_index = len(self._song.tracks) - 1 if index == -1 else index
        track = self._song.tracks[new_index]
        return {"index": new_index, "name": track.name}

    def _delete_track(self, track_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index %d out of range (total: %d)" % (
                track_index, len(self._song.tracks)))
        track_name = self._song.tracks[track_index].name
        self._song.delete_track(track_index)
        return {"deleted_index": track_index, "name": track_name}

    def _set_track_name(self, track_index, name):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        self._song.tracks[track_index].name = name
        return {"name": self._song.tracks[track_index].name}

    def _create_clip(self, track_index, clip_index, length):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if slot.has_clip:
            try:
                slot.delete_clip()
            except Exception:
                pass
        slot.create_clip(length)
        return {"name": slot.clip.name, "length": slot.clip.length}

    def _add_notes_to_clip(self, track_index, clip_index, notes):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot")
        clip = slot.clip
        return {"note_count": self._append_notes(clip, notes)}

    def _append_notes(self, clip, notes):
        """Append notes to a MIDI clip. Never replaces existing notes.

        Live 11+/12 add_new_notes() takes Live.Clip.MidiNoteSpecification
        objects and appends. There is deliberately NO fallback to the legacy
        set_notes(): it replaces every note, so a silent fallback would make
        chunked adds keep only the last chunk. Any failure here propagates.
        """
        import Live
        if not hasattr(clip, "add_new_notes") or \
                not hasattr(Live.Clip, "MidiNoteSpecification"):
            raise RuntimeError(
                "add_new_notes/MidiNoteSpecification not available "
                "(needs Live 11+); refusing the replace-all set_notes fallback")
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

    def _find_arrangement_clip(self, track_index, start_time):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        for clip in track.arrangement_clips:
            if abs(clip.start_time - float(start_time)) < 1e-6:
                return clip
        raise ValueError("No arrangement clip at beat %.3f on track %d"
                         % (float(start_time), track_index))

    def _add_notes_to_arrangement_clip(self, track_index, start_time, notes):
        """Append a chunk of notes to an existing arrangement clip (keeps each
        command well inside the 10 s timeout)."""
        clip = self._find_arrangement_clip(track_index, start_time)
        return {"note_count": self._append_notes(clip, notes)}

    def _get_arrangement_clip_notes(self, track_index, start_time):
        """Read every note of an arrangement clip back, for note-by-note checks."""
        clip = self._find_arrangement_clip(track_index, start_time)
        raw = clip.get_notes_extended(
            from_pitch=int(0), pitch_span=int(128),
            from_time=float(0.0), time_span=float(clip.length))
        notes = [
            {
                "pitch": int(n.pitch),
                "start_time": float(n.start_time),
                "duration": float(n.duration),
                "velocity": int(n.velocity),
                "mute": bool(n.mute),
            }
            for n in raw
        ]
        return {"notes": notes, "note_count": len(notes),
                "clip_length": float(clip.length)}

    def _list_commands(self):
        """Report what this loaded copy supports and which file it came from."""
        return {
            "script": "AbletonMCP",
            "version": SCRIPT_VERSION,
            "source_sha256": _SOURCE_SHA256,
            "file": __file__,
            "commands": sorted(COMMAND_NAMES),
        }

    def _create_arrangement_clip(self, track_index, start_time, length, name, notes):
        """Create a MIDI clip in Arrangement View and append notes to it.

        start_time/length are in beats (song time). Refuses to overlap any
        existing arrangement clip on the track (Live would trim/overwrite it).
        Returns the note count read back from Live, not just what was sent.
        """
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if not track.has_midi_input:
            raise ValueError("Track %d is not a MIDI track" % track_index)
        if not hasattr(track, "create_midi_clip"):
            raise RuntimeError("Track.create_midi_clip not available in this Live version")
        start_time = float(start_time)
        length = float(length)
        if start_time < 0.0 or length <= 0.0:
            raise ValueError("start_time must be >= 0 and length > 0")
        end_time = start_time + length
        for existing in track.arrangement_clips:
            if existing.start_time < end_time and existing.end_time > start_time:
                raise ValueError(
                    "Arrangement range %.3f-%.3f on track %d overlaps existing "
                    "clip '%s'; refusing to overwrite"
                    % (start_time, end_time, track_index, existing.name))

        track.create_midi_clip(start_time, length)

        # Don't rely on the return value: find the clip we just created.
        clip = self._find_arrangement_clip(track_index, start_time)
        if name:
            clip.name = name

        written = self._append_notes(clip, notes) if notes else 0
        readback = clip.get_notes_extended(
            from_pitch=int(0), pitch_span=int(128),
            from_time=float(0.0), time_span=float(clip.length))
        return {
            "track_index": track_index,
            "name": clip.name,
            "start_time": float(clip.start_time),
            "end_time": float(clip.end_time),
            "length": float(clip.length),
            "notes_sent": written,
            "notes_readback": len(readback),
        }

    def _replace_notes_in_clip(self, track_index, clip_index, notes):
        """Replace all MIDI notes in a clip without recreating the clip."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot")
        clip = slot.clip

        # Live 11 exposes remove_notes(from_time, from_pitch, time_span,
        # pitch_span). Live 12 adds remove_notes_extended with equivalent
        # semantics. Cover the complete MIDI range and clip duration.
        duration = max(float(getattr(clip, "length", 0.0)), 0.001)
        try:
            clip.remove_notes_extended(0.0, 0, duration, 128)
        except AttributeError:
            clip.remove_notes(0.0, 0, duration, 128)

        return self._add_notes_to_clip(track_index, clip_index, notes)

    def _delete_clip(self, track_index, clip_index):
        """Delete a Session View clip for proposal undo."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            return {"deleted": False}
        slot.delete_clip()
        return {"deleted": True}

    def _set_clip_name(self, track_index, clip_index, name):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot")
        slot.clip.name = name
        return {"name": slot.clip.name}

    def _set_tempo(self, tempo):
        self._song.tempo = tempo
        return {"tempo": self._song.tempo}

    def _fire_clip(self, track_index, clip_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot")
        slot.fire()
        return {"fired": True}

    def _stop_clip(self, track_index, clip_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        track.clip_slots[clip_index].stop()
        return {"stopped": True}

    def _start_playback(self):
        self._song.start_playing()
        return {"playing": self._song.is_playing}

    def _stop_playback(self):
        self._song.stop_playing()
        return {"playing": self._song.is_playing}

    # ── Mixer controls ────────────────────────────────────────────────────────

    def _set_track_volume(self, track_index, volume):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        # Live's volume parameter range is 0.0 (silence) to 1.0 (unity/default)
        track.mixer_device.volume.value = float(max(0.0, min(1.0, volume)))
        return {"track_index": track_index, "volume": track.mixer_device.volume.value}

    def _set_send_level(self, track_index, send_index, value):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        sends = track.mixer_device.sends
        if send_index < 0 or send_index >= len(sends):
            raise IndexError("Send index %d out of range (track has %d sends)" % (send_index, len(sends)))
        sends[send_index].value = float(max(0.0, min(1.0, value)))
        return {
            "track_index": track_index,
            "send_index": send_index,
            "value": sends[send_index].value,
        }

    def _mute_track(self, track_index, muted):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        track.mute = bool(muted)
        return {"track_index": track_index, "muted": track.mute}

    def _set_track_arm(self, track_index, arm):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if track.can_be_armed:
            track.arm = bool(arm)
        return {"track_index": track_index, "arm": track.arm}

    def _set_device_parameter(self, track_type, track_index, device_name, parameter_name, value):
        if track_type == "return":
            if track_index < 0 or track_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")
            track = self._song.return_tracks[track_index]
        elif track_type == "master":
            track = self._song.master_track
        else:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            
        for device in track.devices:
            if device.name == device_name:
                for param in device.parameters:
                    if param.name == parameter_name:
                        param.value = float(value)
                        return {"status": "success", "device": device_name, "parameter": parameter_name, "value": param.value}
        raise ValueError("Device %s or parameter %s not found" % (device_name, parameter_name))

    def _create_scene(self, index):
        # index=-1 appends at end; Live's create_scene takes the index
        if index == -1:
            index = len(self._song.scenes)
        self._song.create_scene(index)
        return {"scene_index": index, "total_scenes": len(self._song.scenes)}

    def _fire_scene(self, scene_index):
        if scene_index < 0 or scene_index >= len(self._song.scenes):
            raise IndexError("Scene index %d out of range" % scene_index)
        self._song.scenes[scene_index].fire()
        return {"fired": True, "scene_index": scene_index}

    def _set_scene_name(self, scene_index, name):
        if scene_index < 0 or scene_index >= len(self._song.scenes):
            raise IndexError("Scene index %d out of range" % scene_index)
        self._song.scenes[scene_index].name = name
        return {"scene_index": scene_index, "name": self._song.scenes[scene_index].name}

    def _get_session_scenes(self):
        """Return a list of all scenes with their index, name, and tempo."""
        scenes = []
        for idx, scene in enumerate(self._song.scenes):
            scenes.append({
                "index": idx,
                "name": scene.name,
                "tempo": scene.tempo if hasattr(scene, "tempo") else None,
            })
        return {"scenes": scenes, "total": len(scenes)}

    def _get_clip_notes(self, track_index, clip_index):
        """Return all MIDI notes in a clip as a list of note dicts."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index %d out of range" % track_index)
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index %d out of range" % clip_index)
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            return {"notes": [], "note_count": 0}
        clip = slot.clip

        # Live 12+ has get_notes_extended(); Live 11 uses get_notes()
        try:
            raw_notes = clip.get_notes_extended(
                from_pitch=int(0), pitch_span=int(128),
                from_time=float(0.0), time_span=float(clip.length))
            notes = [
                {
                    "pitch": int(n.pitch),
                    "start_time": float(n.start_time),
                    "duration": float(n.duration),
                    "velocity": int(n.velocity),
                    "mute": bool(n.mute),
                }
                for n in raw_notes
            ]
        except AttributeError:
            # Fallback: Live 11 API
            raw_notes = clip.get_notes(0.0, 0, clip.length, 128)
            notes = [
                {
                    "pitch": int(n[0]),
                    "start_time": float(n[1]),
                    "duration": float(n[2]),
                    "velocity": int(n[3]),
                    "mute": bool(n[4]) if len(n) > 4 else False,
                }
                for n in raw_notes
            ]

        return {"notes": notes, "note_count": len(notes), "clip_length": clip.length}

    # ── Browser Helpers ───────────────────────────────────────────────────────

    def _get_browser_item(self, uri, path):
        app = self.application()
        if not app:
            raise RuntimeError("Could not access Live application")
        result = {"uri": uri, "path": path, "found": False}

        if uri:
            item = self._find_browser_item_by_uri(app.browser, uri)
            if item:
                result.update({"found": True, "item": {
                    "name": item.name, "is_folder": item.is_folder,
                    "is_device": item.is_device, "is_loadable": item.is_loadable,
                    "uri": item.uri,
                }})
                return result

        if path:
            parts = path.split("/")
            root_map = {
                "instruments": "instruments", "sounds": "sounds",
                "drums": "drums", "audio_effects": "audio_effects",
                "midi_effects": "midi_effects",
            }
            root_key = parts[0].lower() if parts else ""
            browser_attr = root_map.get(root_key, "instruments")
            current = getattr(app.browser, browser_attr, None)
            if current is None:
                result["error"] = "Category not found: %s" % parts[0]
                return result
            for part in parts[1:]:
                if not part:
                    continue
                found = False
                for child in current.children:
                    if child.name.lower() == part.lower():
                        current = child
                        found = True
                        break
                if not found:
                    result["error"] = "Path part not found: %s" % part
                    return result
            result.update({"found": True, "item": {
                "name": current.name, "is_folder": current.is_folder,
                "is_device": current.is_device, "is_loadable": current.is_loadable,
                "uri": current.uri,
            }})
        return result

    def _load_browser_item(self, track_index, item_uri):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        app = self.application()
        item = self._find_browser_item_by_uri(app.browser, item_uri)
        if not item:
            raise ValueError("Browser item not found: %s" % item_uri)
        self._song.view.selected_track = track
        app.browser.load_item(item)
        return {
            "loaded": True,
            "item_name": item.name,
            "track_name": track.name,
            "uri": item_uri,
        }

    def _load_device_by_name(self, track_index, name):
        """Load a device onto a track by searching user_library and midi_effects by name."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        app = self.application()
        browser = app.browser

        def search_by_name(node, target, depth=0):
            if depth > 6:
                return None
            node_name = getattr(node, "name", "") or ""
            if node_name.lower() == target.lower():
                if getattr(node, "is_loadable", False):
                    return node
            if hasattr(node, "children"):
                for child in node.children:
                    found = search_by_name(child, target, depth + 1)
                    if found:
                        return found
            return None

        # Search user_library first (fast), then midi_effects
        item = None
        for root in (
            getattr(browser, "user_library", None),
            getattr(browser, "midi_effects", None),
            getattr(browser, "max_for_live", None),
        ):
            if root is not None:
                item = search_by_name(root, name)
                if item:
                    break

        if not item:
            raise ValueError("Device not found by name: %s" % name)

        self._song.view.selected_track = track
        browser.load_item(item)
        return {
            "loaded": True,
            "item_name": item.name,
            "track_name": track.name,
            "uri": getattr(item, "uri", ""),
        }

    def _find_browser_item_by_uri(self, node, uri, max_depth=10, depth=0):
        if hasattr(node, "uri") and node.uri == uri:
            return node
        if depth >= max_depth:
            return None
        if hasattr(node, "instruments"):
            for cat in (node.instruments, node.sounds, node.drums,
                        node.audio_effects, node.midi_effects):
                found = self._find_browser_item_by_uri(cat, uri, max_depth, depth + 1)
                if found:
                    return found
            return None
        if hasattr(node, "children"):
            for child in node.children:
                found = self._find_browser_item_by_uri(child, uri, max_depth, depth + 1)
                if found:
                    return found
        return None

    def get_browser_tree(self, category_type="all"):
        app = self.application()
        if not app:
            raise RuntimeError("Could not access Live application")
        if not hasattr(app, "browser") or app.browser is None:
            raise RuntimeError("Browser not available")

        def process_item(item):
            if not item:
                return None
            return {
                "name": item.name if hasattr(item, "name") else "Unknown",
                "is_folder": hasattr(item, "children") and bool(item.children),
                "is_device": hasattr(item, "is_device") and item.is_device,
                "is_loadable": hasattr(item, "is_loadable") and item.is_loadable,
                "uri": item.uri if hasattr(item, "uri") else None,
                "children": [],
            }

        browser = app.browser
        result = {"type": category_type, "categories": []}
        category_map = {
            "instruments": ("Instruments", browser.instruments if hasattr(browser, "instruments") else None),
            "sounds": ("Sounds", browser.sounds if hasattr(browser, "sounds") else None),
            "drums": ("Drums", browser.drums if hasattr(browser, "drums") else None),
            "audio_effects": ("Audio Effects", browser.audio_effects if hasattr(browser, "audio_effects") else None),
            "midi_effects": ("MIDI Effects", browser.midi_effects if hasattr(browser, "midi_effects") else None),
        }
        for key, (label, source) in category_map.items():
            if category_type not in ("all", key):
                continue
            if source is None:
                continue
            try:
                entry = process_item(source)
                if entry:
                    entry["name"] = label
                    result["categories"].append(entry)
            except Exception as e:
                self.log_message("Error processing %s: %s" % (key, str(e)))
        return result

    def get_browser_items_at_path(self, path):
        app = self.application()
        if not app:
            raise RuntimeError("Could not access Live application")
        if not hasattr(app, "browser") or app.browser is None:
            raise RuntimeError("Browser not available")

        parts = [p for p in path.split("/") if p]
        if not parts:
            raise ValueError("Invalid path")

        root_key = parts[0].lower()
        root_map = {
            "instruments": app.browser.instruments if hasattr(app.browser, "instruments") else None,
            "sounds": app.browser.sounds if hasattr(app.browser, "sounds") else None,
            "drums": app.browser.drums if hasattr(app.browser, "drums") else None,
            "audio_effects": app.browser.audio_effects if hasattr(app.browser, "audio_effects") else None,
            "midi_effects": app.browser.midi_effects if hasattr(app.browser, "midi_effects") else None,
        }
        current = root_map.get(root_key)
        if current is None:
            return {
                "path": path,
                "error": "Unknown category: %s" % root_key,
                "items": [],
            }

        for part in parts[1:]:
            if not hasattr(current, "children"):
                return {"path": path, "error": "No children at this level", "items": []}
            found = False
            for child in current.children:
                if hasattr(child, "name") and child.name.lower() == part.lower():
                    current = child
                    found = True
                    break
            if not found:
                return {"path": path, "error": "Path part not found: %s" % part, "items": []}

        items = []
        if hasattr(current, "children"):
            for child in current.children:
                items.append({
                    "name": child.name if hasattr(child, "name") else "Unknown",
                    "is_folder": hasattr(child, "children") and bool(child.children),
                    "is_device": hasattr(child, "is_device") and child.is_device,
                    "is_loadable": hasattr(child, "is_loadable") and child.is_loadable,
                    "uri": child.uri if hasattr(child, "uri") else None,
                })

        return {
            "path": path,
            "name": current.name if hasattr(current, "name") else "Unknown",
            "uri": current.uri if hasattr(current, "uri") else None,
            "is_folder": True,
            "items": items,
        }

    # ── Scene management helpers ──────────────────────────────────────────────

    def _create_scene_with_name(self, name):
        """Create a new scene at the end of the session and set its name."""
        scenes = self._song.scenes
        self._song.create_scene(len(scenes))
        new_scene = self._song.scenes[-1]
        new_scene.name = name          # let a failure raise: wrong section names break the build
        if new_scene.name != name:
            raise ValueError("Scene name not applied: wanted %r, Live has %r"
                             % (name, new_scene.name))
        return {"scene_index": len(self._song.scenes) - 1, "name": name}

    def _get_session_grid(self):
        """
        Return the full session view clip matrix.
        For each track × scene slot: whether a clip exists, its name, and length.
        """
        result = {"tracks": [], "scene_count": len(self._song.scenes)}
        for t_idx, track in enumerate(self._song.tracks):
            track_info = {
                "index": t_idx,
                "name":  track.name,
                "clips": [],
            }
            clip_slots = track.clip_slots
            for s_idx, slot in enumerate(clip_slots):
                has_clip = slot.has_clip
                clip_info = {
                    "scene_index": s_idx,
                    "has_clip":    has_clip,
                }
                if has_clip and slot.clip:
                    clip = slot.clip
                    clip_info["name"]   = clip.name if hasattr(clip, "name") else ""
                    clip_info["length"] = clip.length if hasattr(clip, "length") else 0.0
                    clip_info["is_midi"]= clip.is_midi_clip if hasattr(clip, "is_midi_clip") else False
                track_info["clips"].append(clip_info)
            result["tracks"].append(track_info)
        return result

    def _duplicate_clip_to_scene(self, src_track_index, src_clip_index, dst_scene_index):
        """Duplicate a clip from one scene slot to another scene in the same track."""
        try:
            track     = self._song.tracks[src_track_index]
            src_slot  = track.clip_slots[src_clip_index]
            if not src_slot.has_clip:
                return {"ok": False, "error": "Source slot has no clip"}

            # Ensure destination scene exists
            while len(self._song.scenes) <= dst_scene_index:
                self._song.create_scene(len(self._song.scenes))

            dst_slot = track.clip_slots[dst_scene_index]
            src_slot.duplicate_clip_to(dst_slot)
            return {"ok": True, "dst_scene_index": dst_scene_index}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Misc Helpers ──────────────────────────────────────────────────────────

    def _get_drum_rack_pads(self, track_index):
        """Return loaded Drum Rack pads (note + name) for kit-aware remapping.

        Walks track devices AND nested Instrument Rack chains — many kits
        (e.g. "Percussion Core Kit") wrap a Drum Rack inside a rack, so a
        top-level-only scan finds zero pads.
        """
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index %d out of range" % track_index)
        track = self._song.tracks[track_index]
        pads = []
        debug = []

        def _collect_from_device(device, depth=0):
            found = []
            try:
                can_pads = getattr(device, "can_have_drum_pads", False)
                debug.append(
                    "d=%d name=%r can_pads=%r" % (depth, getattr(device, "name", "?"), can_pads)
                )
                if can_pads:
                    drum_pads = list(getattr(device, "drum_pads", []) or [])
                    debug.append("d=%d drum_pads=%d" % (depth, len(drum_pads)))
                    for pad in drum_pads:
                        try:
                            chains = list(getattr(pad, "chains", []) or [])
                            note = int(pad.note)
                            name = ""
                            try:
                                name = str(pad.name or "")
                            except Exception as exc:
                                debug.append("pad.name err note=%d: %r" % (note, exc))
                            if not name and chains:
                                try:
                                    name = str(chains[0].name or "")
                                except Exception:
                                    pass
                            # Prefer pads that actually have content. A bare
                            # default name like "C1" with no chains is unused.
                            if not chains:
                                continue
                            # Skip Ableton's empty-pad default names (just a note label).
                            if name and len(name) <= 4 and name[0] in "ABCDEFG":
                                # still keep if it has chains (real sample)
                                pass
                            found.append({
                                "note": note,
                                "name": name,
                                "chains": len(chains),
                            })
                        except Exception as exc:
                            debug.append("pad error: %r" % exc)
                    return found
                # Nested Instrument / Audio Effect racks
                if getattr(device, "can_have_chains", False):
                    chains = list(getattr(device, "chains", []) or [])
                    debug.append("d=%d nested_chains=%d" % (depth, len(chains)))
                    for chain in chains:
                        try:
                            for nested in list(getattr(chain, "devices", []) or []):
                                found.extend(_collect_from_device(nested, depth + 1))
                                if found:
                                    return found
                        except Exception as exc:
                            debug.append("chain error: %r" % exc)
            except Exception as exc:
                debug.append("device error: %r" % exc)
            return found

        for device in track.devices:
            pads = _collect_from_device(device, 0)
            if pads:
                break

        pads.sort(key=lambda p: p["note"])
        try:
            self.log_message(
                "get_drum_rack_pads track=%d count=%d debug=%s"
                % (track_index, len(pads), " | ".join(debug)[:500])
            )
        except Exception:
            pass
        return {"pads": pads, "count": len(pads), "debug": debug[:20]}

    def _get_device_type(self, device):
        try:
            if device.can_have_drum_pads:
                return "drum_machine"
            if device.can_have_chains:
                return "rack"
            name = device.class_display_name.lower()
            if "instrument" in name:
                return "instrument"
            if "audio_effect" in device.class_name.lower():
                return "audio_effect"
            if "midi_effect" in device.class_name.lower():
                return "midi_effect"
        except Exception:
            pass
        return "unknown"
