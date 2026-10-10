"""LiveBackend against a fake Remote Script (NOT real Live: only checks protocol use and the safety guard)."""
import json
import socket
import threading

from stemforge.analyze.pipeline import analyze
from stemforge.build.backends import LiveBackend, build, compare_notes
from stemforge.build.plan import make_plan


class FakeLive:
    def __init__(self):
        self.tracks = ["Existing 1", "Existing 2"]     # pre-existing user tracks must never change
        self.scenes = ["Scene A"]
        self.clips = {}
        self.log = []
        self.srv = socket.socket(); self.srv.bind(("127.0.0.1", 0)); self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def handle(self, cmd, p):
        self.log.append((cmd, p))
        if cmd == "get_session_info":
            return {"track_count": len(self.tracks), "scene_count": len(self.scenes)}
        if cmd == "set_tempo":
            return {}
        if cmd == "create_midi_track":
            self.tracks.append("MIDI"); return {"index": len(self.tracks) - 1}
        if cmd == "set_track_name":
            self.tracks[p["track_index"]] = p["name"]; return {}
        if cmd == "create_scene_with_name":
            self.scenes.append(p["name"]); return {"scene_index": len(self.scenes) - 1}
        if cmd == "create_clip":
            self.clips[(p["track_index"], p["clip_index"])] = []; return {}
        if cmd == "set_clip_name":
            return {}
        if cmd == "add_notes_to_clip":
            self.clips[(p["track_index"], p["clip_index"])] += p["notes"]; return {}
        if cmd == "get_clip_notes":
            return {"notes": self.clips.get((p["track_index"], p["clip_index"]), [])}
        raise KeyError(cmd)

    def serve(self):
        conn, _ = self.srv.accept()
        while True:
            data = conn.recv(1 << 20)
            if not data:
                return
            msg = json.loads(data.decode())
            try:
                resp = {"status": "success", "result": self.handle(msg["type"], msg["params"])}
            except Exception as e:
                resp = {"status": "error", "message": "unknown command %s" % e}
            conn.sendall(json.dumps(resp).encode())


def test_session_build_and_readback(song):
    folder, _ = song
    bp = analyze(str(folder), log=lambda *_: None)
    plan = make_plan(bp, "session")
    fake = FakeLive()
    backend = LiveBackend(port=fake.port)
    res = build(plan, backend, log=lambda *_: None)
    assert fake.tracks[:2] == ["Existing 1", "Existing 2"]          # untouched
    assert set(res["tracks"].values()) == set(range(2, 2 + len(plan.tracks)))
    for stem, sec, cid, *_ in plan.placements:
        got = backend.read_back(res["tracks"][stem], res["scenes"][sec])
        assert compare_notes(plan.clips[cid]["notes"], got)["match"]
    assert all(len(p["notes"]) <= LiveBackend.CHUNK for c, p in fake.log if c == "add_notes_to_clip")
