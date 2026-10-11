import mido
import pytest

from stemforge.analyze.pipeline import analyze
from stemforge.importmidi import import_into_blueprint, read_notes


def _midi(path, bpm, notes, tpb=480):
    mid = mido.MidiFile(ticks_per_beat=tpb)
    tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
    t = 0
    for pitch, start_beat, dur_beat in notes:
        on = int(start_beat * tpb)
        tr.append(mido.Message("note_on", note=pitch, velocity=90, time=on - t)); t = on
        off = int((start_beat + dur_beat) * tpb)
        tr.append(mido.Message("note_off", note=pitch, velocity=0, time=off - t)); t = off
    mid.save(str(path))


def test_read_notes_by_time_ignores_file_tempo(tmp_path):
    f = tmp_path / "a.mid"
    _midi(f, 60.0, [(40, 4.0, 1.0)])          # 60 BPM: beat 4 is at 4.0 s
    notes, bpm, _ = read_notes(str(f))
    assert bpm == pytest.approx(60.0)
    assert notes[0]["start_s"] == pytest.approx(4.0) and notes[0]["end_s"] == pytest.approx(5.0)


def test_import_replaces_stem_notes_and_rederives_clips(song, tmp_path):
    folder, _ = song
    bp = analyze(str(folder), log=lambda *_: None)
    stem = next(s for s in bp["stems"] if s["role"] == "bass")
    f = tmp_path / "bass.mid"
    secs = 60.0 / bp["global"]["tempo"]
    _midi(f, bp["global"]["tempo"], [(36, 40.0, 1.0), (38, 44.0, 1.0)])   # bars 11 and 12: bass is playing there
    r = import_into_blueprint(bp, stem["name"], str(f), log=lambda *_: None)
    tr = stem["transcription"]
    assert r["notes"] == len(tr["notes"]) >= 2
    assert all(n["source"] == "imported" and n["confidence"] == 1.0 for n in tr["notes"])
    assert tr["backend"].startswith("imported:")
    assert {n["pitch"] for c in bp["clips"] if c["stem"] == stem["name"] for n in c["notes"]} == {36, 38}


def test_import_unknown_stem_lists_choices(song, tmp_path):
    folder, _ = song
    bp = analyze(str(folder), log=lambda *_: None)
    f = tmp_path / "x.mid"; _midi(f, 124.0, [(40, 0, 1)])
    with pytest.raises(ValueError, match="stems are"):
        import_into_blueprint(bp, "nope", str(f), log=lambda *_: None)
