"""The clean rebuild on synthetic stems with a known answer: where the hits are, what note, how the loops are cleaned."""
import json

import numpy as np
import soundfile as sf

from stemforge import blueprint, resynth

SR = 22050
BPM = 120.0
BEAT = 60.0 / BPM


def riff(path, steps=(1, 5, 9, 13), bars=8, midi=38, harmonics=(2, 3, 4, 5), swing=0.0, loud=None):
    """A mono riff whose FUNDAMENTAL is filtered away (only harmonics 2..5 present), like a low-cut synth stab."""
    y = np.zeros(int((bars * 4 * BEAT + 1.0) * SR), dtype="float32")
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    for bar in range(bars):
        for st in steps:
            t = bar * 4 * BEAT + (st // 4) * BEAT + (st % 4) * BEAT / 4 + (swing * BEAT if st % 2 else 0.0)
            n = int(0.12 * SR)
            tt = np.arange(n) / SR
            amp = 0.5 if loud is None else loud.get((bar, st), 0.5)
            fade = np.minimum(1.0, (n - np.arange(n)) / (0.02 * SR))      # no click at the end, like a real note
            burst = sum(np.sin(2 * np.pi * f0 * h * tt) / h for h in harmonics) * np.exp(-tt * 28) * amp * fade
            i = int(t * SR)
            y[i:i + n] += burst.astype("float32")[: len(y) - i]
    sf.write(path, y, SR)
    return path


def beats(bars=8):
    return [k * BEAT for k in range(bars * 4 + 8)]


GROOVE = {"swing_pct": 50.0, "e_position_beats": 0.25, "a_position_beats": 0.75, "grid_offset_beats": 0.0}


def test_snap_uses_the_songs_measured_swing_positions():
    b = np.array(beats())
    # a hit 0.294 beats after beat 3 is the swung 'e' (step 1), not a straight 0.25
    assert resynth.snap_step(b[3] + 0.294 * BEAT, b, 0.0, 0.294, 0.786) == (3, 1, np.float64(0.0)) or \
        resynth.snap_step(b[3] + 0.294 * BEAT, b, 0.0, 0.294, 0.786)[:2] == (3, 1)
    assert resynth.snap_step(b[3] + 0.05 * BEAT, b, 0.05, 0.294, 0.786)[:2] == (3, 0)      # constant offset removed
    assert resynth.snap_step(b[3] + 0.99 * BEAT, b, 0.0, 0.25, 0.75)[:2] == (4, 0)          # rounds to the next downbeat


def test_hits_pitch_and_register_are_recovered_even_with_the_fundamental_filtered_away(tmp_path):
    p = riff(str(tmp_path / "keys.wav"), steps=(1, 5, 9, 13), midi=38)
    ev = resynth.extract_events(p, beats(), GROOVE, 30, 90)
    steps = {resynth.step_of(e) for e in ev}
    assert steps == {1, 5, 9, 13}, steps
    assert len(ev) >= 28                                       # 8 bars x 4 hits, a missed hit or two tolerated
    midis = {e["pitches"][0][0] for e in ev}
    assert midis == {38}, midis                                # D2, not the D3 that the loudest harmonic suggests
    assert all(0.1 <= e["dur"] <= 2.0 for e in ev)


def test_swung_hits_land_on_the_swung_step(tmp_path):
    p = riff(str(tmp_path / "sw.wav"), steps=(1, 3, 5, 7), swing=0.04, midi=38)
    g = {**GROOVE, "e_position_beats": 0.29, "a_position_beats": 0.79}
    ev = resynth.extract_events(p, beats(), g, 30, 90)
    assert {resynth.step_of(e) for e in ev} == {1, 3, 5, 7}


def test_clean_loops_drops_a_stray_hit_and_keeps_a_real_fill():
    def hit(bar, step, s=0.8, p=38):
        return {"beat": bar * 4 + step // 4, "step": step % 4, "strength": s, "pitches": [(p, 1.0)], "t": 0.0, "dur": 0.2,
                "level_db": 0.0}
    base = [1, 5, 9, 13]
    ev = [hit(b, s) for b in range(8) for s in base]
    ev.append(hit(2, 6, 0.3))                                   # a delay tail in bar 2
    ev += [hit(7, s) for s in (3, 7, 11, 15)]                   # bar 7 is a genuinely different fill
    ev = [e for e in ev if not (e["beat"] // 4 == 7 and (e["beat"] % 4) * 4 + e["step"] in base)]
    out = resynth.clean_loops(ev, 0, 8)
    bar2 = {resynth.step_of(e) for e in out if resynth.bar_of(e) == 2}
    bar7 = {resynth.step_of(e) for e in out if resynth.bar_of(e) == 7}
    assert bar2 == set(base)                                    # the stray hit is gone
    assert bar7 == {3, 7, 11, 15}                               # the fill survives


def test_velocity_is_the_rank_of_loudness_and_notes_are_inside_the_section():
    vm = resynth.velocity_map([-30.0, -20.0, -10.0, 0.0])
    assert vm(-30.0) < vm(-10.0) < vm(0.0) and 46 <= vm(-30.0) and vm(0.0) <= 118
    ev = [{"beat": 3, "step": 3, "strength": 0.5, "pitches": [(38, 1.0)], "t": 0.0, "dur": 1.5, "level_db": -5.0}]
    notes = resynth.to_notes(ev, 0, 1, 58.7, vel_fn=vm)
    assert notes and notes[0]["start"] > 3.7 and notes[0]["pitch"] == 38
    assert resynth.to_notes(ev, 0, 1, 50.0, octave=1)[0]["pitch"] == 50


def test_quiet_layer_still_plays_but_true_silence_does_not():
    def ev(bar, n, db):
        return [{"beat": bar * 4 + i // 4, "step": i % 4, "strength": 0.5, "pitches": [(38, 1.0)], "t": 0.0, "dur": 0.2,
                 "level_db": db} for i in range(n)]
    events = ev(0, 8, -9.0) + ev(1, 8, 0.0) + ev(2, 8, 0.0) + ev(3, 1, -30.0)
    quiet = {"start_bar": 0, "length_bars": 1}
    silent = {"start_bar": 3, "length_bars": 1}
    assert resynth._layer_plays(events, quiet, analyzer_says_active=False)          # 9 dB down, 8 hits: still the song
    assert not resynth._layer_plays(events, silent, analyzer_says_active=False)
    assert resynth._layer_plays(events, silent, analyzer_says_active=True)          # the analyzer's yes is trusted


def _mini_blueprint(tmp_path):
    p_bass = riff(str(tmp_path / "bass.wav"), steps=(1, 2, 5, 6, 9, 10, 13, 14), midi=26, harmonics=(1, 2, 3))
    p_syn = riff(str(tmp_path / "synth.wav"), steps=(1, 5, 7, 9, 13), midi=38)
    secs = [{"index": 0, "start_bar": 0, "length_bars": 4, "energy_db": -5.0, "energy_slope_db_per_bar": 0.0,
             "active_stems": ["bass", "synth"], "evidence": [], "label": "groove", "name": "01 GROOVE | 4"},
            {"index": 1, "start_bar": 4, "length_bars": 4, "energy_db": -5.0, "energy_slope_db_per_bar": 0.0,
             "active_stems": ["bass", "synth"], "evidence": [], "label": "groove", "name": "02 GROOVE | 4"}]
    stems = [{"name": "bass", "role": "bass", "path": p_bass, "mode": "mono", "transcription": {"skipped": False, "notes": []}},
             {"name": "synth", "role": "synth", "path": p_syn, "mode": "poly", "transcription": {"skipped": False, "notes": []}},
             {"name": "kick", "role": "kick", "path": None, "mode": "drums", "transcription": {"skipped": False, "notes": []}}]
    kick = {"id": "k0", "stem": "kick", "name": "kick", "length_beats": 16.0, "loop_period_bars": None, "used_in": [0],
            "notes": [{"pitch": 36, "start": float(b), "duration": 0.1, "velocity": 100, "confidence": 1.0} for b in range(0, 16, 1)]}
    bp = {"schema_version": 1, "song": {"name": "t", "source_dir": str(tmp_path), "duration_s": 20.0},
          "global": {"tempo": BPM, "n_bars": 8, "time_signature": [4, 4], "beats_s": beats(), "key": {}},
          "sections": secs, "stems": stems, "warnings": [], "clips": [kick],
          "placements": [{"stem": "kick", "section": 0, "clip": "k0"}], "clip_min_confidence": 0.0}
    idea = {"schema": "stemforge.idea/1", "groove": GROOVE, "sections": secs, "roles": {s["name"]: s["role"] for s in stems}}
    return bp, idea


def test_rebuild_is_deterministic_cached_and_valid(tmp_path):
    bp, idea = _mini_blueprint(tmp_path)
    cache = str(tmp_path / "events.json")
    a = resynth.rebuild(bp, idea, log=lambda *_: None, cache_path=cache)
    blueprint.validate(a)
    assert (tmp_path / "events.json").exists()
    b = resynth.rebuild(bp, idea, log=lambda *_: None, cache_path=cache)          # from the saved reading
    assert a["clips"] == b["clips"]
    assert {s["name"] for s in a["stems"]} == {"kick", "R Bass", "R Synth"}
    bass = [n for c in a["clips"] if c["stem"] == "R Bass" for n in c["notes"]]
    assert bass and {n["pitch"] for n in bass} == {26}
    up = resynth.rebuild(bp, idea, log=lambda *_: None, cache_path=cache, octaves={"bass": 1})
    assert {n["pitch"] for c in up["clips"] if c["stem"] == "R Bass" for n in c["notes"]} == {38}
    chk = resynth.check_against_audio(bp, a)
    assert chk["R Synth"]["hit_match"] >= 0.7 and chk["R Bass"]["hit_match"] >= 0.7


def test_rare_semitone_neighbours_are_snapped_but_real_notes_stay():
    def e(p):
        return {"beat": 0, "step": 0, "strength": 0.5, "pitches": [(p, 1.0)], "t": 0.0}
    evs = [e(26)] * 60 + [e(25)] * 2 + [e(29)] * 8 + [e(38)] * 5
    evs = [dict(x, pitches=list(x["pitches"])) for x in evs]
    n = resynth.snap_outliers(evs)
    pitches = [x["pitches"][0][0] for x in evs]
    assert n == 2 and 25 not in pitches                       # the rare neighbour is gone
    assert pitches.count(29) == 8 and pitches.count(38) == 5   # real notes (a third away, an octave away) stay
    mixed = [e(26)] * 5 + [e(27)] * 5
    assert resynth.snap_outliers([dict(x) for x in mixed]) == 0   # no dominant pitch: nothing is changed
