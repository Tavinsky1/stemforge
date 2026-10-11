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


def test_build_never_changes_set_tempo_unless_asked(song):
    folder, _ = song
    plan = make_plan(analyze(str(folder), log=lambda *_: None), "session")

    class TempoFake(FakeLive):
        def handle(self, cmd, p):
            if cmd == "get_session_info":
                return {"track_count": len(self.tracks), "scene_count": len(self.scenes), "tempo": 90.0}
            return super().handle(cmd, p)

    fake = TempoFake()
    build(plan, LiveBackend(port=fake.port), log=lambda *_: None)
    assert "set_tempo" not in [c for c, _ in fake.log]            # the set's tempo is left alone
    fake2 = TempoFake()
    build(plan, LiveBackend(port=fake2.port), log=lambda *_: None, set_tempo=True)
    assert "set_tempo" in [c for c, _ in fake2.log]               # only when asked


def test_arrangement_refused_when_set_tempo_differs(song):
    import pytest
    from stemforge.build.backends import NotSupported
    folder, _ = song
    plan = make_plan(analyze(str(folder), log=lambda *_: None), "arrangement")

    class TempoFake(FakeLive):
        def handle(self, cmd, p):
            if cmd == "get_session_info":
                return {"track_count": 2, "scene_count": 1, "tempo": plan.tempo + 10}
            if cmd == "list_commands":
                return {"commands": ["create_arrangement_clip", "add_notes_to_arrangement_clip",
                                     "get_arrangement_clip_notes"]}
            return super().handle(cmd, p)

    fake = TempoFake()
    with pytest.raises(NotSupported, match="BPM"):
        build(plan, LiveBackend(port=fake.port), log=lambda *_: None)
    assert "create_midi_track" not in [c for c, _ in fake.log]    # refused before creating anything


class FakeLiveWithClaim(FakeLive):
    """Like the real script v2: empty unnamed leading rows can be claimed; anything else is refused."""
    def __init__(self, scenes):
        super().__init__()
        self.scenes = list(scenes)          # "" = empty unnamed row, anything else = the owner's scene
        self.claimed = []

    def handle(self, cmd, p):
        if cmd == "list_commands":
            return {"commands": ["claim_scene", "create_scene_with_name"], "version": "stemforge-script-2"}
        if cmd == "claim_scene":
            i = p["scene_index"]
            if self.scenes[i] != "":
                raise RuntimeError("PermissionError: Scene %d is named %r" % (i, self.scenes[i]))
            self.scenes[i] = p["name"]; self.claimed.append(i)
            return {"scene_index": i, "name": p["name"], "claimed": True}
        return super().handle(cmd, p)


def test_session_build_starts_at_scene_one_by_reusing_empty_rows(song):
    folder, _ = song
    plan = make_plan(analyze(str(folder), log=lambda *_: None), "session")
    fake = FakeLiveWithClaim(["", "", ""])
    backend = LiveBackend(port=fake.port)
    res = build(plan, backend, log=lambda *_: None)
    n = len(plan.scenes)
    assert res["scenes"] == {i: i for i in range(n)}                   # section 1 is scene row 0, in order, no gaps
    assert fake.scenes[:min(3, n)] == plan.scenes[:min(3, n)] and len(fake.scenes) == max(3, n)
    assert fake.claimed == list(range(min(3, n)))


def test_build_stops_reusing_rows_at_the_first_owner_row(song):
    folder, _ = song
    plan = make_plan(analyze(str(folder), log=lambda *_: None), "session")
    fake = FakeLiveWithClaim(["", "OWNER SCENE", ""])
    backend = LiveBackend(port=fake.port)
    res = build(plan, backend, log=lambda *_: None)
    assert fake.scenes[1] == "OWNER SCENE" and fake.claimed == [0]    # owner row untouched, row 2 not reused
    assert res["scenes"][0] == 0 and res["scenes"][1] == 3            # the rest appended after all existing rows
