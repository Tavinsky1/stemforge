"""smoke-live against a fake Remote Script. Not real Live: checks the test logic itself,
in particular that it FAILS when note adds replace instead of append (the 12.2.1 bug)."""
from .test_live_backend import FakeLive

from stemforge import smoke
from stemforge.cli import main


class SmokeFake(FakeLive):
    replace_on_add = False        # True mimics legacy set_notes(): each add replaces all notes
    COMMANDS = sorted(smoke.REQUIRED)

    def handle(self, cmd, p):
        if cmd == "list_commands":
            return {"version": "fake-1", "source_sha256": "ab" * 32, "file": "/fake/__init__.py",
                    "commands": self.COMMANDS}
        if cmd == "create_arrangement_clip":
            self.arr = getattr(self, "arr", {})
            self.arr[(p["track_index"], p["start_time"])] = list(p["notes"]); return {}
        if cmd == "add_notes_to_arrangement_clip":
            key = (p["track_index"], p["start_time"])
            self.arr[key] = list(p["notes"]) if self.replace_on_add else self.arr[key] + p["notes"]
            return {"note_count": len(p["notes"])}
        if cmd == "get_arrangement_clip_notes":
            return {"notes": self.arr[(p["track_index"], p["start_time"])]}
        if cmd == "add_notes_to_clip" and self.replace_on_add:
            self.clips[(p["track_index"], p["clip_index"])] = list(p["notes"]); return {}
        return super().handle(cmd, p)


def test_smoke_passes_when_adds_append():
    fake = SmokeFake()
    rep = smoke.run(port=fake.port, log=lambda *_: None)
    assert rep["ok"], rep
    assert fake.tracks[:2] == ["Existing 1", "Existing 2"]
    assert fake.tracks[rep["track_index"]] == smoke.SMOKE_TRACK     # left for inspection


def test_smoke_fails_when_adds_replace():
    fake = SmokeFake()
    fake.replace_on_add = True
    rep = smoke.run(port=fake.port, log=lambda *_: None)
    assert not rep["ok"]
    assert [s["step"] for s in rep["steps"]][-1] == "session chunked append"   # stops at first failure


def test_smoke_flags_old_remote_script():
    fake = SmokeFake()
    fake.COMMANDS = [c for c in smoke.REQUIRED if c != "create_arrangement_clip"]
    rep = smoke.run(port=fake.port, log=lambda *_: None)
    assert not rep["ok"] and rep["steps"][0]["missing"] == ["create_arrangement_clip"]


def test_smoke_uses_its_own_scene_and_never_an_existing_row():
    fake = SmokeFake()
    rep = smoke.run(port=fake.port, log=lambda *_: None)
    assert rep["ok"] and rep["scene_index"] == len(fake.scenes) - 1 and fake.scenes[-1] == smoke.SMOKE_TRACK
    assert (rep["track_index"], rep["scene_index"]) in fake.clips
    assert (rep["track_index"], 0) not in fake.clips            # not in "Scene A", which was already in the set
    assert not any(c in ("delete_track", "delete_clip") for c, _ in fake.log)


def test_cli_refuses_without_confirm_scratch(capsys):
    assert main(["smoke-live"]) == 2
    assert "--confirm-set-ok" in capsys.readouterr().out
