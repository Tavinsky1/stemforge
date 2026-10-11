"""Builder backends. DryRun prints, MidiFiles writes .mid, Live talks to the AbletonMCP Remote Script on TCP 9877."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from .plan import Plan


class NotSupported(RuntimeError):
    pass


class Backend:
    modifies_set = False      # True for backends that write into someone's open Live set
    session_tempo = None      # the open set's tempo, when the backend can read it

    def start(self, plan: Plan): ...
    def set_tempo(self, bpm: float): ...
    def create_track(self, name: str, role: str) -> int: ...
    def create_scene(self, name: str) -> int: ...
    def create_session_clip(self, track: int, scene: int, name: str, length: float, notes: list[dict]): ...
    def place_arrangement_clip(self, track: int, name: str, start_beat: float, length: float, notes: list[dict]): ...
    def finish(self): ...


def build(plan: Plan, backend: Backend, roles: dict[str, str] | None = None, log=print,
          set_tempo: bool = False) -> dict:
    """Run the plan on a backend. Only ever creates NEW tracks/scenes; never touches existing ones.
    A backend that writes into someone's open set (Live) does NOT change that set's tempo unless set_tempo=True."""
    roles = roles or {}
    backend.start(plan)
    if not backend.modifies_set or set_tempo:
        backend.set_tempo(plan.tempo)
    elif backend.session_tempo is not None and abs(backend.session_tempo - plan.tempo) > 0.5:
        msg = ("the open set is at %.2f BPM but the song is %.2f BPM" % (backend.session_tempo, plan.tempo))
        if plan.mode == "arrangement":
            raise NotSupported(msg + "; arrangement clips are placed in beats, so they would drift away from the audio. "
                               "Pass --set-tempo to change the set's tempo, or use --mode session.")
        log("WARNING: " + msg + "; leaving the set's tempo alone (pass --set-tempo to match the song).")
    track_idx = {n: backend.create_track(n, roles.get(n, "")) for n in plan.tracks}
    scene_idx = {}
    if plan.mode == "session":
        for i, name in enumerate(plan.scenes):
            scene_idx[i] = backend.create_scene(name)
    n_clips = n_notes = 0
    for stem, sec, cid, start, length, name in plan.placements:
        c = plan.clips[cid]
        if plan.mode == "session":
            backend.create_session_clip(track_idx[stem], scene_idx[sec], name, length, c["notes"])
        else:
            backend.place_arrangement_clip(track_idx[stem], name, start, length, c["notes"])
        n_clips += 1
        n_notes += len(c["notes"])
    backend.finish()
    return {"tracks": track_idx, "scenes": scene_idx, "clips": n_clips, "notes": n_notes}


class DryRunBackend(Backend):
    def __init__(self, log=print):
        self.log = log
        self._t = 0
        self._s = 0

    def start(self, plan):
        self.log("DRY RUN (%s mode): nothing will be created in Live" % plan.mode)

    def set_tempo(self, bpm):
        self.log("set tempo %.2f" % bpm)

    def create_track(self, name, role):
        self.log("new MIDI track [%d] '%s'" % (self._t, name))
        self._t += 1
        return self._t - 1

    def create_scene(self, name):
        self.log("new scene [%d] '%s'" % (self._s, name))
        self._s += 1
        return self._s - 1

    def create_session_clip(self, track, scene, name, length, notes):
        self.log("  clip track %d scene %d '%s' %.0f beats, %d notes" % (track, scene, name, length, len(notes)))

    def place_arrangement_clip(self, track, name, start_beat, length, notes):
        self.log("  arrangement clip track %d at beat %.0f '%s' %.0f beats, %d notes" % (track, start_beat, name, length, len(notes)))


class MidiFilesBackend(Backend):
    """Fallback that needs no Live connection: one .mid per section plus full.mid; drag them into Live."""

    def __init__(self, out_dir: str, song: str = "song"):
        self.out = Path(out_dir)
        self.song = song
        self.tracks: list[tuple[str, str]] = []
        self.scenes: list[str] = []
        self.items: list[tuple] = []   # (track, scene_or_None, start_beat, name, length, notes)
        self.tempo = 120.0

    def start(self, plan):
        self.out.mkdir(parents=True, exist_ok=True)

    def set_tempo(self, bpm):
        self.tempo = bpm

    def create_track(self, name, role):
        self.tracks.append((name, role))
        return len(self.tracks) - 1

    def create_scene(self, name):
        self.scenes.append(name)
        return len(self.scenes) - 1

    def create_session_clip(self, track, scene, name, length, notes):
        self.items.append((track, scene, None, name, length, notes))

    def place_arrangement_clip(self, track, name, start_beat, length, notes):
        self.items.append((track, None, start_beat, name, length, notes))

    def _write(self, path: Path, events_by_track: dict[int, list[tuple]], total_beats: float):
        import mido
        tpb = 480
        mid = mido.MidiFile(ticks_per_beat=tpb)
        meta = mido.MidiTrack()
        meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(self.tempo)))
        meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
        mid.tracks.append(meta)
        for ti, (name, role) in enumerate(self.tracks):
            ev = events_by_track.get(ti)
            if not ev:
                continue
            tr = mido.MidiTrack()
            tr.append(mido.MetaMessage("track_name", name=name))
            ch = 9 if role in ("drums", "kick", "snare", "hat") else min(ti, 8)
            msgs = []
            for pitch, start, dur, vel in ev:
                msgs.append((int(round(start * tpb)), 1, mido.Message("note_on", note=pitch, velocity=vel, channel=ch)))
                msgs.append((int(round((start + dur) * tpb)), 0, mido.Message("note_off", note=pitch, velocity=0, channel=ch)))
            msgs.sort(key=lambda m: (m[0], m[1]))
            last = 0
            for t, _, m in msgs:
                m.time = t - last
                last = t
                tr.append(m)
            mid.tracks.append(tr)
        mid.save(str(path))

    def finish(self):
        # one file per scene (session view)
        for si, sname in enumerate(self.scenes):
            ev: dict[int, list] = {}
            for track, scene, _, _, _, notes in self.items:
                if scene == si:
                    ev.setdefault(track, []).extend((n["pitch"], n["start"], n["duration"], n["velocity"]) for n in notes)
            safe = "".join(c if c.isalnum() or c in "-_ |" else "_" for c in sname).replace(" | ", "_").replace(" ", "_")
            self._write(self.out / ("%s_%s.mid" % (self.song, safe)), ev, 0)
        # full timeline (arrangement view): needs start beats
        ev = {}
        for track, scene, start, _, _, notes in self.items:
            if start is not None:
                ev.setdefault(track, []).extend((n["pitch"], start + n["start"], n["duration"], n["velocity"]) for n in notes)
        if ev:
            self._write(self.out / ("%s_full.mid" % self.song), ev, 0)


class LiveBackend(Backend):
    """
    Talks to the AbletonMCP Remote Script (TCP 9877, JSON {"type","params"}).
    Session mode uses commands the Remote Script already has. Arrangement mode needs a command
    ("create_arrangement_clip") that must be added to the Remote Script after checking the Live 12.2.1 LOM.
    Only new tracks/scenes are created; existing ones are never modified.
    """
    CHUNK = 80   # notes per add_notes_to_clip call (crash prevention)
    modifies_set = True

    def __init__(self, host="127.0.0.1", port=9877, timeout=15.0, log=print):
        self.host, self.port, self.timeout, self.log = host, port, timeout, log
        self.created_tracks: list[int] = []
        self.created_scenes: list[int] = []
        self.sock = None

    # --- transport
    def _connect(self):
        if self.sock is None:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)

    def send(self, cmd: str, params: dict | None = None) -> dict:
        self._connect()
        self.sock.sendall(json.dumps({"type": cmd, "params": params or {}}).encode())
        buf = b""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            try:
                resp = json.loads(buf.decode())
                break
            except json.JSONDecodeError:
                continue
        else:
            raise TimeoutError("no reply to %s" % cmd)
        if resp.get("status") == "error":
            msg = resp.get("message", "")
            if "unknown" in msg.lower() or "unsupported" in msg.lower():
                raise NotSupported("Remote Script does not support '%s' (%s)" % (cmd, msg))
            raise RuntimeError("%s failed: %s" % (cmd, msg))
        return resp.get("result", resp)

    def available_commands(self) -> set[str]:
        """Probe so we can fail early (before creating anything) when a needed command is missing."""
        try:
            r = self.send("list_commands")
            return set(r.get("commands", []))
        except Exception:
            return set()

    # --- backend API
    def start(self, plan):
        info = self.send("get_session_info")
        self.log("connected to Live: %s tracks, %s scenes" % (info.get("track_count", "?"), info.get("scene_count", "?")))
        self.scene_base = info.get("scene_count")
        self.session_tempo = info.get("tempo")
        if plan.mode == "arrangement":
            cmds = self.available_commands()
            need = {"create_arrangement_clip", "add_notes_to_arrangement_clip", "get_arrangement_clip_notes"}
            if need - cmds:
                raise NotSupported("arrangement mode needs Remote Script commands %s (not installed). "
                                   "Use --mode session, or --backend midi for .mid files. See HANDOVER_CLAUDE_CODE.md."
                                   % sorted(need - cmds))

    def set_tempo(self, bpm):
        self.send("set_tempo", {"tempo": bpm})

    def create_track(self, name, role):
        r = self.send("create_midi_track", {"index": -1})
        idx = r["index"]
        self.send("set_track_name", {"track_index": idx, "name": name})
        self.created_tracks.append(idx)
        return idx

    def create_scene(self, name):
        r = self.send("create_scene_with_name", {"name": name})
        self.created_scenes.append(r["scene_index"])
        return r["scene_index"]

    def _guard(self, track=None, scene=None):
        if track is not None and track not in self.created_tracks:
            raise RuntimeError("refusing to touch track %d: not created by this run" % track)
        if scene is not None and scene not in self.created_scenes:
            raise RuntimeError("refusing to touch scene %d: not created by this run" % scene)

    @staticmethod
    def _cmd_notes(notes):
        return [{"pitch": n["pitch"], "start_time": n["start"], "duration": n["duration"],
                 "velocity": n["velocity"], "mute": False} for n in notes]

    def create_session_clip(self, track, scene, name, length, notes):
        self._guard(track, scene)
        self.send("create_clip", {"track_index": track, "clip_index": scene, "length": float(length)})
        self.send("set_clip_name", {"track_index": track, "clip_index": scene, "name": name})
        for i in range(0, len(notes), self.CHUNK):
            self.send("add_notes_to_clip", {"track_index": track, "clip_index": scene,
                                            "notes": self._cmd_notes(notes[i:i + self.CHUNK])})

    def place_arrangement_clip(self, track, name, start_beat, length, notes):
        self._guard(track)
        self.send("create_arrangement_clip", {"track_index": track, "start_time": float(start_beat),
                                              "length": float(length), "name": name, "notes": []})
        for i in range(0, len(notes), self.CHUNK):
            self.send("add_notes_to_arrangement_clip", {"track_index": track, "start_time": float(start_beat),
                                                        "notes": self._cmd_notes(notes[i:i + self.CHUNK])})

    # --- Phase 3 read-back
    def read_back(self, track: int, scene: int) -> list[dict]:
        r = self.send("get_clip_notes", {"track_index": track, "clip_index": scene})
        return r.get("notes", [])

    def read_back_arrangement(self, track: int, start_beat: float) -> list[dict]:
        r = self.send("get_arrangement_clip_notes", {"track_index": track, "start_time": float(start_beat)})
        return r.get("notes", [])


def compare_notes(expected: list[dict], got: list[dict], tol: float = 0.01) -> dict:
    """Compare blueprint notes with notes read back from Live."""
    exp = sorted((n["pitch"], round(n["start"], 3), round(n["duration"], 3), n["velocity"]) for n in expected)
    act = sorted((n["pitch"], round(n.get("start_time", n.get("start", 0)), 3), round(n["duration"], 3), n["velocity"]) for n in got)
    missing, extra = [], list(act)
    for e in exp:
        for a in extra:
            if a[0] == e[0] and abs(a[1] - e[1]) <= tol and abs(a[2] - e[2]) <= tol and a[3] == e[3]:
                extra.remove(a)
                break
        else:
            missing.append(e)
    return {"expected": len(exp), "got": len(act), "missing": missing, "extra": extra, "match": not missing and not extra}
