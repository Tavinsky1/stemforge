import numpy as np

from stemforge import blueprint
from stemforge.analyze.pipeline import analyze
from stemforge.build.backends import DryRunBackend, MidiFilesBackend, LiveBackend, NotSupported, build, compare_notes
from stemforge.build.plan import make_plan
from stemforge.discover import discover, classify


def test_classify():
    assert classify("Song (Bass)") == "bass"
    assert classify("12 Vocals") == "vocals"
    assert classify("Drums") == "drums"
    assert classify("hi-hats") == "hat"
    assert classify("mystery") == "other"


def test_discover(song):
    folder, _ = song
    roles = {s.name: s.role for s in discover(folder)}
    assert roles == {"drums_kick": "kick", "hats": "hat", "bass": "bass", "synth_lead": "synth"}


def test_analyze_end_to_end(song, tmp_path):
    folder, truth = song
    bp = analyze(str(folder), log=lambda *_: None)
    g = bp["global"]
    assert abs(g["tempo"] - 124.0) < 1.5
    labels = [s["label"] for s in bp["sections"]]
    starts = [s["start_bar"] for s in bp["sections"]]
    # drums leave at bar 16 and return at 24: those boundaries must be found (+-1 bar)
    assert any(abs(b - 16) <= 1 for b in starts), starts
    assert any(abs(b - 24) <= 1 for b in starts), starts
    assert "breakdown" in labels
    # bass notes: D2(38)/F2(41)/C2(36) come back
    bass = next(s for s in bp["stems"] if s["name"] == "bass")["transcription"]["notes"]
    assert bass, "no bass notes (pyin fallback should handle mono)"
    pcs = {n["pitch"] % 12 for n in bass}
    assert pcs <= {2, 5, 0, 1, 3, 4}  # mostly D, F, C; allow neighbours
    kick = next(s for s in bp["stems"] if s["name"] == "drums_kick")["transcription"]["notes"]
    assert all(n["pitch"] == 36 for n in kick)
    assert abs(len(kick) - len(truth["kick"])) <= 6
    # blueprint round trip + clip reuse
    p = tmp_path / "bp.json"
    blueprint.save(bp, p)
    bp2 = blueprint.load(p)
    assert len(bp2["placements"]) >= len(bp2["clips"])


def test_polyphonic_without_backend_invents_nothing(song):
    folder, _ = song
    from stemforge.analyze import pitched
    try:
        import basic_pitch  # noqa
        return
    except ImportError:
        pass
    notes, backend, warnings = pitched.transcribe(str(folder / "synth_lead.wav"), np.zeros(10), 22050, "synth", "poly")
    assert notes == [] and warnings


def test_build_backends(song, tmp_path):
    folder, _ = song
    bp = analyze(str(folder), log=lambda *_: None)
    plan = make_plan(bp, "session")
    logs = []
    res = build(plan, DryRunBackend(log=logs.append))
    assert res["clips"] == len(plan.placements) and any("new scene" in l for l in logs)
    res = build(make_plan(bp, "arrangement"), MidiFilesBackend(str(tmp_path / "mid"), "t"))
    assert (tmp_path / "mid" / "t_full.mid").exists()
    build(plan, MidiFilesBackend(str(tmp_path / "mid2"), "t"))
    assert len(list((tmp_path / "mid2").glob("*.mid"))) == len(plan.scenes)


def test_compare_notes():
    a = [{"pitch": 60, "start": 0.0, "duration": 1.0, "velocity": 90}]
    assert compare_notes(a, [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 90}])["match"]
    assert not compare_notes(a, [])["match"]


def test_live_backend_refuses_foreign_tracks():
    b = LiveBackend()
    b.created_tracks = [5]
    import pytest
    with pytest.raises(RuntimeError):
        b._guard(track=0)
