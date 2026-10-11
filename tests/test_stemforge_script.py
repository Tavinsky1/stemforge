"""Behaviour of Stemforge's Ableton script against stand-ins for Live's objects (no Live, no sockets)."""
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ableton" / "Stemforge" / "__init__.py"


# ---- stand-ins for Live's API
class Spec:
    def __init__(self, pitch, start_time, duration, velocity=100.0, mute=False, **_):
        assert isinstance(pitch, int)
        self.pitch, self.start_time, self.duration, self.velocity, self.mute = pitch, start_time, duration, velocity, mute


class FakeClip:
    def __init__(self, start=0.0, length=4.0):
        self.name, self.length, self.start_time, self.end_time, self.notes = "", length, start, start + length, []

    def add_new_notes(self, specs):
        for s in specs:
            assert isinstance(s, Spec), "must be MidiNoteSpecification, not %r" % type(s)
            self.notes.append(s)

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        return list(self.notes)


class FakeSlot:
    def __init__(self):
        self.clip = None

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        assert self.clip is None, "Live itself refuses a second clip"
        self.clip = FakeClip(0.0, length)


_ptr = iter(range(1000, 10 ** 6))


class FakeTrack:
    def __init__(self, name, n_scenes):
        self.name, self.has_midi_input, self._live_ptr = name, True, next(_ptr)
        self.clip_slots = [FakeSlot() for _ in range(n_scenes)]
        self.arrangement_clips = []

    def create_midi_clip(self, start, length):
        self.arrangement_clips.append(FakeClip(start, length))


class FakeScene:
    def __init__(self, name="", max_len=None):
        self._name, self.max_len, self._live_ptr = name, max_len, next(_ptr)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, v):
        self._name = v[: self.max_len] if self.max_len else v


class FakeSong:
    def __init__(self):
        self.tempo, self.signature_numerator, self.signature_denominator = 120.0, 4, 4
        self.scenes = [FakeScene("Scene A")]
        self.tracks = [FakeTrack("Existing 1", 1), FakeTrack("Existing 2", 1)]
        self.tracks[0].clip_slots[0].create_clip(4.0)
        self.tracks[0].clip_slots[0].clip.add_new_notes([Spec(60, 0.0, 1.0)])
        self.tracks[0].arrangement_clips.append(FakeClip(0.0, 8.0))
        self.scene_name_limit = None

    def create_midi_track(self, index):
        assert index == -1
        self.tracks.append(FakeTrack("MIDI", len(self.scenes)))

    def create_scene(self, index):
        self.scenes.insert(index, FakeScene(max_len=self.scene_name_limit))
        for t in self.tracks:
            t.clip_slots.insert(index, FakeSlot())


@pytest.fixture()
def sf(monkeypatch):
    class FakeCS:
        def __init__(self, c_instance):
            self._c = c_instance
        def song(self): return self._c
        def log_message(self, m): pass
        def show_message(self, m): pass
        def schedule_message(self, d, fn): fn()
        def disconnect(self): pass

    fw = types.ModuleType("_Framework"); cs = types.ModuleType("_Framework.ControlSurface"); cs.ControlSurface = FakeCS
    live = types.ModuleType("Live"); live.Clip = types.SimpleNamespace(MidiNoteSpecification=Spec)
    for name, mod in (("_Framework", fw), ("_Framework.ControlSurface", cs), ("Live", live)):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("stemforge_script_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.Stemforge, "start_server", lambda self: None)     # never bind a port in tests
    song = FakeSong()
    inst = mod.Stemforge(song)
    inst.song_obj = song
    inst.mod = mod
    return inst


def notes(n, start=0):
    return [{"pitch": 40 + start + i, "start_time": (start + i) * 0.5, "duration": 0.25, "velocity": 90, "mute": False}
            for i in range(n)]


def new_track_and_scene(sf):
    t = sf.execute("create_midi_track", {})["index"]
    s = sf.execute("create_scene_with_name", {"name": "stemforge_smoke"})["scene_index"]
    return t, s


def test_commands_match_dispatcher_and_report_no_delete(sf):
    assert set(sf.mod.COMMAND_NAMES) == set(sf._handlers)
    r = sf.execute("list_commands", {})
    assert r["script"] == "Stemforge" and r["port"] == 9878 and r["can_delete"] is False
    assert r["version"].startswith("stemforge-script-") and len(r["source_sha256"]) == 64
    assert r["file"].endswith("Stemforge/__init__.py")


@pytest.mark.parametrize("cmd", ["delete_track", "delete_clip", "delete_scene", "load_instrument_or_effect",
                                 "load_browser_item", "set_device_parameter", "fire_clip", "fire_scene",
                                 "start_playback", "set_track_volume", "create_audio_track", "replace_notes_in_clip"])
def test_destructive_and_unrelated_commands_do_not_exist(sf, cmd):
    with pytest.raises(ValueError, match="Unknown command"):
        sf.execute(cmd, {})


def test_source_has_no_destructive_calls():
    code = "\n".join(l for l in SCRIPT.read_text().splitlines() if not l.lstrip().startswith("#"))
    for pat in (r"\.delete_\w+\(", r"set_notes\(", r"remove_notes", r"duplicate_\w+\(", r"\.fire\(",
                r"load_item", r"create_audio_track", r"MidiNote\("):
        assert not re.search(pat, code), pat


def test_never_writes_to_tracks_it_did_not_create(sf):
    for cmd, p in (("set_track_name", {"track_index": 0, "name": "x"}),
                   ("create_clip", {"track_index": 1, "clip_index": 0, "length": 4}),
                   ("add_notes_to_clip", {"track_index": 0, "clip_index": 0, "notes": notes(1)}),
                   ("create_arrangement_clip", {"track_index": 1, "start_time": 64.0, "length": 4.0}),
                   ("add_notes_to_arrangement_clip", {"track_index": 0, "start_time": 0.0, "notes": notes(1)})):
        with pytest.raises(PermissionError, match="not created by Stemforge"):
            sf.execute(cmd, p)
    song = sf.song_obj
    assert [t.name for t in song.tracks] == ["Existing 1", "Existing 2"]
    assert len(song.tracks[0].clip_slots[0].clip.notes) == 1 and len(song.tracks[0].arrangement_clips) == 1


def test_clip_must_be_in_a_scene_stemforge_created(sf):
    t = sf.execute("create_midi_track", {})["index"]
    with pytest.raises(PermissionError, match="Scene 0"):
        sf.execute("create_clip", {"track_index": t, "clip_index": 0, "length": 4})     # your scene row


def test_session_flow_appends_chunks_and_reads_back(sf):
    t, s = new_track_and_scene(sf)
    assert sf.execute("set_track_name", {"track_index": t, "name": "1 Bass"})["name"] == "1 Bass"
    sf.execute("create_clip", {"track_index": t, "clip_index": s, "length": 8.0})
    sf.execute("set_clip_name", {"track_index": t, "clip_index": s, "name": "bass groove"})
    sf.execute("add_notes_to_clip", {"track_index": t, "clip_index": s, "notes": notes(6)})
    assert sf.execute("get_clip_notes", {"track_index": t, "clip_index": s})["note_count"] == 6
    sf.execute("add_notes_to_clip", {"track_index": t, "clip_index": s, "notes": notes(6, start=6)})
    got = sf.execute("get_clip_notes", {"track_index": t, "clip_index": s})
    assert got["note_count"] == 12                       # appended, not replaced
    assert sorted(n["pitch"] for n in got["notes"]) == list(range(40, 52))


def test_never_overwrites_a_clip(sf):
    t, s = new_track_and_scene(sf)
    sf.execute("create_clip", {"track_index": t, "clip_index": s, "length": 4})
    with pytest.raises(ValueError, match="never overwrites"):
        sf.execute("create_clip", {"track_index": t, "clip_index": s, "length": 4})


def test_arrangement_flow_and_overlap_refused(sf):
    t, _ = new_track_and_scene(sf)
    r = sf.execute("create_arrangement_clip", {"track_index": t, "start_time": 16.0, "length": 8.0, "name": "a"})
    assert r["start_time"] == 16.0 and r["end_time"] == 24.0 and r["notes_sent"] == 0
    sf.execute("add_notes_to_arrangement_clip", {"track_index": t, "start_time": 16.0, "notes": notes(6)})
    sf.execute("add_notes_to_arrangement_clip", {"track_index": t, "start_time": 16.0, "notes": notes(6, start=6)})
    assert sf.execute("get_arrangement_clip_notes", {"track_index": t, "start_time": 16.0})["note_count"] == 12
    with pytest.raises(ValueError, match="never overwrites"):
        sf.execute("create_arrangement_clip", {"track_index": t, "start_time": 20.0, "length": 8.0})
    sf.execute("create_arrangement_clip", {"track_index": t, "start_time": 24.0, "length": 8.0})   # touching is fine


def test_reads_work_on_any_track(sf):
    assert sf.execute("get_clip_notes", {"track_index": 0, "clip_index": 0})["note_count"] == 1
    info = sf.execute("get_session_info", {})
    assert info["track_count"] == 2 and not any(t["created_by_stemforge"] for t in info["tracks"])


def test_scene_rename_must_stick(sf):
    sf.song_obj.scene_name_limit = 3
    with pytest.raises(ValueError, match="Scene name not applied"):
        sf.execute("create_scene_with_name", {"name": "13 OUTRO | 52"})


def test_tempo_is_range_checked(sf):
    assert sf.execute("set_tempo", {"tempo": 126.0})["tempo"] == 126.0
    with pytest.raises(ValueError):
        sf.execute("set_tempo", {"tempo": 5})


# --- claim_scene: start a build at scene 1 by reusing completely empty rows -----------------------------------------

def _song_with_empty_rows(sf, n=3):
    song = sf.song_obj
    for _ in range(n):
        song.create_scene(len(song.scenes))
    return len(song.scenes) - n          # index of the first empty row (row 0 'Scene A' holds a clip and a name)


def test_claim_scene_takes_an_empty_unnamed_row_and_allows_clips(sf):
    first = _song_with_empty_rows(sf)
    t = sf.execute("create_midi_track", {})["index"]
    r = sf.execute("claim_scene", {"scene_index": first, "name": "Intro"})
    assert r["claimed"] and sf.song_obj.scenes[first].name == "Intro"
    sf.execute("create_clip", {"track_index": t, "clip_index": first, "length": 4})
    sf.execute("add_notes_to_clip", {"track_index": t, "clip_index": first, "notes": notes(3)})
    assert len(sf.execute("get_clip_notes", {"track_index": t, "clip_index": first})["notes"]) == 3


def test_claim_scene_refuses_named_rows_and_rows_with_clips_and_changes_nothing(sf):
    song = sf.song_obj
    before = [(s.name, [bool(t.clip_slots[i].has_clip) for t in song.tracks]) for i, s in enumerate(song.scenes)]
    with pytest.raises(PermissionError):
        sf.execute("claim_scene", {"scene_index": 0, "name": "Intro"})            # 'Scene A' is named and has a clip
    first = _song_with_empty_rows(sf, 2)
    song.scenes[first]._name = "My drop"
    with pytest.raises(PermissionError, match="My drop"):
        sf.execute("claim_scene", {"scene_index": first, "name": "Intro"})
    song.scenes[first + 1]._name = ""
    song.tracks[1].clip_slots[first + 1].create_clip(4.0)                          # the owner's clip in an unnamed row
    with pytest.raises(PermissionError, match="holds a clip"):
        sf.execute("claim_scene", {"scene_index": first + 1, "name": "Intro"})
    assert song.scenes[first]._name == "My drop" and song.tracks[1].clip_slots[first + 1].has_clip
    assert [(s.name, [bool(t.clip_slots[i].has_clip) for t in song.tracks]) for i, s in enumerate(song.scenes)][:1] == before[:1]


def test_claim_scene_refuses_tempo_override_rows(sf):
    first = _song_with_empty_rows(sf, 1)
    sf.song_obj.scenes[first].tempo_enabled = True
    with pytest.raises(PermissionError, match="tempo"):
        sf.execute("claim_scene", {"scene_index": first, "name": "Intro"})


def test_claimed_row_is_the_only_extra_row_clips_may_enter(sf):
    first = _song_with_empty_rows(sf, 2)
    t = sf.execute("create_midi_track", {})["index"]
    sf.execute("claim_scene", {"scene_index": first, "name": "Intro"})
    with pytest.raises(PermissionError, match="Scene"):
        sf.execute("create_clip", {"track_index": t, "clip_index": first + 1, "length": 4})
