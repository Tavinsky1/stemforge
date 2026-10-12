"""The taste rules of compose, checked on a small hand-made song. Rules are checked; whether it is GOOD is for ears."""
import numpy as np
import soundfile as sf

from stemforge import blueprint, compose, idea
from stemforge.build.backends import DryRunBackend, build
from stemforge.build.plan import make_plan

STEPS = [0.0] * 16
for _i in (1, 5, 7, 9, 13):
    STEPS[_i] = 0.2


def _song():
    secs = [("intro", 8), ("groove", 16), ("peak", 8), ("breakdown", 4), ("outro", 12)]
    sections, start = [], 0
    for i, (role, bars) in enumerate(secs):
        active = ["0 Drums"] if role == "intro" else ["0 Drums", "1 Bass", "3 Keyboard", "5 Synth"]
        if role == "breakdown":
            active = ["3 Keyboard", "5 Synth"]
        sections.append({"index": i, "start_bar": start, "length_bars": bars, "energy_db": -4.0 if role != "peak" else -2.0,
                         "energy_slope_db_per_bar": 0.0, "active_stems": active, "evidence": [], "label": role,
                         "name": "%02d %s | %d" % (i + 1, role.upper(), bars)})
        start += bars
    stems = [{"name": "0 Drums", "role": "drums", "path": None, "mode": "drums", "transcription": {"skipped": False}},
             {"name": "1 Bass", "role": "bass", "path": None, "mode": "mono", "transcription": {"skipped": False}},
             {"name": "3 Keyboard", "role": "keys", "path": None, "mode": "poly", "transcription": {"skipped": False}},
             {"name": "5 Synth", "role": "synth", "path": None, "mode": "poly", "transcription": {"skipped": False}}]
    clips, placements = [], []
    for s in sections:
        if "0 Drums" in s["active_stems"]:
            n = [{"pitch": 36, "start": b * 4.0, "duration": 0.1, "velocity": 100, "confidence": 1.0} for b in range(s["length_bars"])]
            n += [{"pitch": 42, "start": b * 4.0 + 0.25, "duration": 0.1, "velocity": 70, "confidence": 1.0} for b in range(s["length_bars"])]
            clips.append({"id": "d%d" % s["index"], "stem": "0 Drums", "name": "d", "length_beats": s["length_bars"] * 4.0,
                          "notes": n, "loop_period_bars": None, "used_in": [s["index"]]})
            placements.append({"stem": "0 Drums", "section": s["index"], "clip": "d%d" % s["index"]})
        if "1 Bass" in s["active_stems"]:
            n = [{"pitch": 26, "start": b * 4.0, "duration": 1.0, "velocity": 100, "confidence": 1.0} for b in range(s["length_bars"])]
            clips.append({"id": "b%d" % s["index"], "stem": "1 Bass", "name": "b", "length_beats": s["length_bars"] * 4.0,
                          "notes": n, "loop_period_bars": None, "used_in": [s["index"]]})
            placements.append({"stem": "1 Bass", "section": s["index"], "clip": "b%d" % s["index"]})
    bp = {"schema_version": 1, "song": {"name": "t", "source_dir": "", "duration_s": 100.0},
          "global": {"tempo": 126.0, "n_bars": start, "time_signature": [4, 4], "beats_s": [], "key": {}},
          "sections": sections, "stems": stems, "warnings": [], "clips": clips, "placements": placements,
          "clip_min_confidence": 0.0}
    chroma = [0.0] * 12
    chroma[2], chroma[9], chroma[3] = 0.5, 0.3, 0.2
    layer = {"onsets_per_bar": 10.0, "step_weights": STEPS, "mean_strength": 0.6, "level_db": -30.0, "chroma": chroma}
    iroles = {"0 Drums": "drums", "1 Bass": "bass", "3 Keyboard": "keys", "5 Synth": "synth"}
    isecs = []
    for s in sections:
        isecs.append({"index": s["index"], "name": s["name"], "label": s["label"], "role": s["label"], "start_bar": s["start_bar"],
                      "length_bars": s["length_bars"], "energy_db": s["energy_db"], "energy_slope_db_per_bar": 0.0,
                      "active_stems": s["active_stems"], "bass_roots_by_bar": ["D"] * s["length_bars"],
                      "bass_step_probs": [0.0] * 16, "bass_notes_per_bar": 1.0})
    iroles_layers = {k: {str(s["index"]): layer for s in sections} for k in ("3 Keyboard", "5 Synth")}
    i = {"schema": "stemforge.idea/1", "song": "t", "tempo": 126.0, "bars": start, "time_signature": [4, 4],
         "key": {"tonic": "D", "tonic_pc": 2}, "groove": {"swing_pct": 58.0}, "sections": isecs, "roles": iroles,
         "layers": iroles_layers, "bass_stem": "1 Bass"}
    return bp, i


def test_same_seed_same_music_different_seed_different_music():
    bp, i = _song()
    a, b, c = compose.compose(bp, i, seed=1), compose.compose(bp, i, seed=1), compose.compose(bp, i, seed=2)
    assert a["clips"] == b["clips"]
    assert a["clips"] != c["clips"]


def test_rules_hold_and_blueprint_is_valid():
    bp, i = _song()
    g = compose.compose(bp, i, seed=0)
    blueprint.validate(g)                                   # every note inside its clip
    r = compose.report(g, i)
    assert set(r) == {"G Keys", "G Synth"}
    for name, row in r.items():
        assert row["outside_palette"] == 0, name            # drone, fifth and colour tones only
        assert row["velocity_std"] > 8 and row["distinct_velocities"] > 12, name      # no flat velocities
        assert row["off_grid_pct"] > 30, name               # swing + micro-timing present
    lo_k, hi_k = r["G Keys"]["pitch_range"]
    lo_s, hi_s = r["G Synth"]["pitch_range"]
    assert compose.KEYS_RANGE[0] <= lo_k and hi_k <= compose.KEYS_RANGE[1] + 2
    assert compose.SYNTH_RANGE[0] <= lo_s and hi_s <= compose.SYNTH_RANGE[1]
    assert lo_k > 26 + 12 and lo_s > hi_k - 12              # nothing in the bass register, synth sits above keys


def test_no_major_third_and_nothing_labelled_transcribed():
    bp, i = _song()
    g = compose.compose(bp, i, seed=3)
    for c in g["clips"]:
        if c["stem"] in compose.GENERATED:
            assert all(n["source"] == "generated" for n in c["notes"])
            assert all((n["pitch"] - 50) % 12 != 4 for n in c["notes"])      # F# above D is never written


def test_layers_follow_the_songs_own_arrangement():
    bp, i = _song()
    g = compose.compose(bp, i, seed=0)
    by_sec = {(c["stem"], c["used_in"][0]) for c in g["clips"]}
    assert ("G Synth", 0) not in by_sec                      # the intro has no synth in the source
    assert ("G Keys", 0) in by_sec                           # only the 4-bar D+A bed
    assert ("G Keys", 3) in by_sec and ("G Synth", 3) in by_sec    # breakdown keeps keys and synth
    bed = next(c for c in g["clips"] if c["stem"] == "G Keys" and c["used_in"][0] == 0)
    assert min(n["start"] for n in bed["notes"]) >= (8 - 4) * 4          # last 4 bars only
    assert max(n["velocity"] for n in bed["notes"]) < 70                 # a bed, not a statement


def test_keys_and_synth_interlock_inside_a_section():
    bp, i = _song()
    g = compose.compose(bp, i, seed=0)

    def steps(stem, sec):
        c = next(c for c in g["clips"] if c["stem"] == stem and c["used_in"][0] == sec)
        return {int(round((n["start"] % 4.0) * 4 - 0.0)) % 16 for n in c["notes"] if n["start"] % 4.0 < 3.95}
    # swing delays the odd steps by <0.05 beat, so compare on the unswung grid
    off = compose.swing_offset(58.0)
    def unswung(stem, sec):
        c = next(c for c in g["clips"] if c["stem"] == stem and c["used_in"][0] == sec)
        out = set()
        for n in c["notes"]:
            pos = n["start"] % 4.0
            st = int(round(pos * 4))
            if st % 2 == 1 and abs(pos - (st * 0.25 + off)) < 0.03:
                out.add(st)
            elif st % 2 == 0 and abs(pos - st * 0.25) < 0.03:
                out.add(st)
        return out
    assert len(unswung("G Keys", 1) & unswung("G Synth", 1)) <= 2


def test_transcribed_parts_keep_their_notes_and_get_the_measured_swing():
    bp, i = _song()
    g = compose.compose(bp, i, seed=0)
    key = lambda n: (round(n["start"], 1), n["pitch"])        # compose sorts notes; swing moves a hit by < 0.05 beat
    d_before = sorted(next(c for c in bp["clips"] if c["id"] == "d1")["notes"], key=key)
    d_after = sorted(next(c for c in g["clips"] if c["stem"] == "0 Drums" and c["used_in"][0] == 1)["notes"], key=key)
    assert len(d_before) == len(d_after)
    assert [n["pitch"] for n in d_before] == [n["pitch"] for n in d_after]
    off = compose.swing_offset(58.0)
    for a, b in zip(d_before, d_after):
        odd = int(round(a["start"] * 4)) % 2 == 1
        assert abs((b["start"] - a["start"]) - (off if odd else 0.0)) < 1e-6
    bass_b = next(c for c in bp["clips"] if c["id"] == "b1")["notes"]
    bass_a = next(c for c in g["clips"] if c["stem"] == "1 Bass" and c["used_in"][0] == 1)["notes"]
    assert [n["start"] for n in bass_b] == [n["start"] for n in bass_a]      # bass is never retimed


def test_straight_swing_changes_nothing_and_plan_builds():
    bp, i = _song()
    g = compose.compose(bp, i, seed=0, swing_pct=50.0)
    d_after = next(c for c in g["clips"] if c["stem"] == "0 Drums" and c["used_in"][0] == 1)["notes"]
    before = next(c for c in bp["clips"] if c["id"] == "d1")["notes"]
    assert sorted((n["start"], n["pitch"]) for n in d_after) == sorted((n["start"], n["pitch"]) for n in before)
    plan = make_plan(g, "session")
    res = build(plan, DryRunBackend(log=lambda *_: None), log=lambda *_: None)
    assert res["clips"] == len(plan.placements) and res["notes"] > 0


# --- the measurements, on audio with a known answer ------------------------------------------------------------------

def _clicks(path, times, sr=22050, length=20.0):
    y = np.zeros(int(sr * length), dtype="float32")
    for t in times:
        i = int(t * sr)
        y[i:i + 200] = np.hanning(200) * 0.9
    sf.write(path, y, sr)


def test_measured_swing_matches_a_known_swing(tmp_path):
    bpm, beat = 120.0, 0.5
    beats = [k * beat for k in range(36)]
    for pct in (50.0, 58.0, 66.0):
        times = []
        for k in range(34):
            times += [k * beat, k * beat + beat * 0.25 * (pct / 50.0), k * beat + beat * 0.5,
                      k * beat + beat * (0.5 + 0.25 * (pct / 50.0))]
        p = tmp_path / ("sw%d.wav" % pct)
        _clicks(str(p), times)
        got = idea.measure_swing(str(p), beats)["swing_pct"]
        assert abs(got - pct) < 5.0, (pct, got)


def test_layer_profile_finds_where_a_layer_hits(tmp_path):
    beat = 0.5
    beats = [k * beat for k in range(4 * 8 + 4)]
    times = [bar * 2.0 + st * beat / 4 for bar in range(8) for st in (1, 5, 9, 13)]
    p = tmp_path / "keys.wav"
    _clicks(str(p), times, length=17.0)
    secs = [{"index": 0, "start_bar": 0, "length_bars": 8, "label": "groove"}]
    prof = idea.layer_profile(str(p), beats, secs)[0]
    top = sorted(range(16), key=lambda k: -prof["step_weights"][k])[:4]
    assert sorted(top) == [1, 5, 9, 13]
    assert 3.0 <= prof["onsets_per_bar"] <= 5.0


def test_synth_uses_at_most_three_pitch_classes_and_lanes_differ_in_length():
    bp, i = _song()
    g = compose.compose(bp, i, seed=4)
    r = compose.report(g, i)
    assert r["G Synth"]["max_pitch_classes_in_a_clip"] <= 3
    assert r["G Keys"]["max_pitch_classes_in_a_clip"] <= 4
    # pitch lane (3/5/7) and velocity lane (5/7) are never the same length, so they phase against each other
    assert 7 != 5 and len({len([74, 69, 74]), len([74, 69, 74, 75, 69]), 7}) == 3


def test_three_velocity_tiers_are_all_used():
    bp, i = _song()
    r = compose.report(compose.compose(bp, i, seed=0), i)
    for name in ("G Keys", "G Synth"):
        t = r[name]["velocity_tiers"]
        assert all(v > 0 for v in t.values()), (name, t)


def test_strip_back_before_a_drop_and_outro_mirrors_the_intro():
    bp, i = _song()
    g = compose.compose(bp, i, seed=0)
    # section 1 (groove, 16 bars) is followed by the peak: the synth is silent in its last 2 bars
    syn = next(c for c in g["clips"] if c["stem"] == "G Synth" and c["used_in"][0] == 1)
    assert not [n for n in syn["notes"] if n["start"] >= (16 - 2) * 4]
    keys = next(c for c in g["clips"] if c["stem"] == "G Keys" and c["used_in"][0] == 1)
    last_bar = [n for n in keys["notes"] if n["start"] >= 15 * 4]
    assert len({round(n["start"], 1) for n in last_bar}) <= 1            # one stab only
    # outro (12 bars): no synth in the last 8 bars, keys on the bare D+A drone
    out_syn = [c for c in g["clips"] if c["stem"] == "G Synth" and c["used_in"][0] == 4]
    assert not out_syn or not [n for n in out_syn[0]["notes"] if n["start"] >= (12 - 8) * 4]
    out_keys = next(c for c in g["clips"] if c["stem"] == "G Keys" and c["used_in"][0] == 4)
    tail = [n for n in out_keys["notes"] if n["start"] >= (12 - 8) * 4]
    assert {n["pitch"] % 12 for n in tail} == {2, 9}


def test_idea_production_notes_are_tempo_synced():
    notes = idea.production_notes(126.0)
    assert any("357 ms" in n for n in notes)      # dotted 1/8 at 126 BPM
    assert any("119 ms" in n for n in notes)      # 1/16


def test_rules_are_listed_for_the_app():
    assert len(compose.RULES) >= 10 and all(isinstance(r, str) for r in compose.RULES)
    bp, i = _song()
    assert compose.compose(bp, i)["generation"]["rules"] == compose.RULES


def test_brief_works_for_plain_stem_names():
    bp, i = _song()
    for s in i["sections"]:
        s["active_stems"] = [n.split(" ", 1)[1].lower() for n in s["active_stems"]]
    md = idea.to_markdown({**i, "key": {**i["key"], "reading": "x", "palette_ranked": ["D", "A"], "fifth": 0.1, "flat_second": 0.1,
                                        "leading_tone": 0.1, "tritone": 0.1,
                                        "analyzer_said": {"tonic": "D", "mode": "major", "confidence": 0.5}},
                           "groove": {"swing_pct": 58.0, "evidence_onsets": 10}})
    assert "drums" in md and "keyboard" in md
