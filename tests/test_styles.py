"""Create-from-zero: deterministic assembly from the style library, with the style rules pinned down."""
import json

import pytest

from stemforge import blueprint
from stemforge.build.backends import DryRunBackend, build
from stemforge.build.plan import make_plan
from stemforge.styles import create as C


def _steps(bp, stem):
    clips = {c["id"]: c for c in bp["clips"]}
    out = []
    for p in bp["placements"]:
        if p["stem"] == stem:
            for n in clips[p["clip"]]["notes"]:
                out.append(int(round((n["start"] % 4.0) * 4)) % 16)
    return out


def test_library_is_complete_and_every_pattern_has_a_source():
    lib = C.library()
    assert set(lib["styles"]) == set(C.STYLES)
    for pid, p in lib["patterns"].items():
        assert p["source"]["kind"] in ("notebooklm", "documented", "measured"), pid
        assert p["source"].get("ref"), pid
        assert p["notes"], pid
    for st, sd in lib["styles"].items():
        for layer, spec in sd["layers"].items():
            for opt in spec["base"]:
                assert all(i in lib["patterns"] for i in opt), (st, layer)


@pytest.mark.parametrize("style", C.STYLES)
def test_every_style_creates_a_valid_blueprint_that_builds(style):
    bp = C.create(style)
    blueprint.validate(bp)
    plan = make_plan(bp, "session")
    res = build(plan, DryRunBackend(log=lambda *_: None), log=lambda *_: None)
    assert res["clips"] > 10 and res["notes"] > 500
    names = {s["name"] for s in bp["stems"]}
    assert {"Kick", "Bass"} <= names
    info = C.style_info(style)
    assert len(bp["sections"]) >= 5 and info["bpm"]["min"] <= bp["global"]["tempo"] <= info["bpm"]["max"]


@pytest.mark.parametrize("style", C.STYLES)
def test_same_seed_same_song_and_new_seeds_give_different_songs(style):
    a, b = C.create(style, seed=7), C.create(style, seed=7)
    assert a["clips"] == b["clips"] and a["global"] == b["global"]
    sigs = {json.dumps(C.create(style, seed=s)["clips"], sort_keys=True) for s in range(1, 21)}
    assert len(sigs) == 20                                       # twenty seeds, twenty different songs
    assert len({C.create(style)["generation"]["seed"] for _ in range(4)}) >= 3          # no seed given -> a new one each time


@pytest.mark.parametrize("style", C.STYLES)
def test_variety_comes_from_sourced_patterns_and_stays_inside_the_style(style):
    info = C.style_info(style)
    lib = C.library()["patterns"]
    keys, bpms, bass_choices, lengths = set(), set(), set(), set()
    for seed in range(1, 25):
        bp = C.create(style, seed=seed)
        blueprint.validate(bp)
        g = bp["generation"]
        keys.add(g["tonic"]); bpms.add(round(g["bpm"])); lengths.add(bp["global"]["n_bars"])
        assert info["bpm"]["min"] <= g["bpm"] <= info["bpm"]["max"]
        assert all(s["length_bars"] % 8 == 0 for s in bp["sections"])            # the 8-bar grid
        for e in g["layers"]:
            for pid in e["pattern"].split("+"):
                assert pid in lib and lib[pid]["source"]["kind"] in ("notebooklm", "documented", "measured")
            if e["layer"] == "bass":
                bass_choices.add(e["pattern"])
        assert not bp["warnings"]
    assert len(keys) >= 3 and len(bpms) >= 4 and len(lengths) >= 4 and len(bass_choices) >= 3


def test_pinned_key_and_tempo_are_respected_while_the_rest_still_varies():
    a, b = C.create("house", tonic="F", bpm=126, seed=1), C.create("house", tonic="F", bpm=126, seed=2)
    assert a["generation"]["tonic"] == b["generation"]["tonic"] == "F" and a["global"]["tempo"] == b["global"]["tempo"] == 126
    assert a["clips"] != b["clips"]


@pytest.mark.parametrize("style", ["techno", "house"])
def test_bass_keeps_off_the_kick_in_every_song_of_the_kick_driven_styles(style):
    for seed in range(1, 21):
        chk = C.create(style, seed=seed)["generation"]["checks"]
        assert chk["bass_on_kick_steps_pct"] <= 30, (style, seed, chk)


def test_techno_bass_is_a_rolling_groove_that_leaves_the_kick_steps_free():
    bp = C.create("techno", seed=11)
    g = bp["generation"]["checks"]
    assert g["bass_on_kick_steps_pct"] < 30                      # documented: the first 16th of every beat is left for the kick
    # across seeds the rolling 16ths groove (the documented and measured one) is among the choices
    assert any(e["pattern"] == "B14" for sd in range(1, 15) for e in C.create("techno", seed=sd)["generation"]["layers"]
               if e["layer"] == "bass")


def test_house_bass_answers_the_kick_on_the_offbeats():
    bp = C.create("house", seed=5)
    g = bp["generation"]["checks"]
    assert g["bass_on_kick_steps_pct"] <= 30
    assert set(_steps(bp, "Kick")) == {0, 4, 8, 12}
    assert set(_steps(bp, "Clap")) == {4, 12}


def test_downtempo_is_not_four_on_the_floor_and_cumbia_keeps_its_percussion():
    dt = C.create("downtempo", seed=6)
    assert set(_steps(dt, "Kick")) != {0, 4, 8, 12}
    cu = C.create("electro_cumbia", seed=6)
    assert "Perc" in {s["name"] for s in cu["stems"]}


def test_key_transposes_only_the_pitched_layers_and_drums_stay_put():
    d = C.create("techno", tonic="C", seed=3)
    g = C.create("techno", tonic="G", seed=3)                   # +7 -> written as -5 to stay in register
    def pitches(bp, stem):
        clips = {c["id"]: c for c in bp["clips"]}
        return sorted({n["pitch"] for p in bp["placements"] if p["stem"] == stem for n in clips[p["clip"]]["notes"]})
    assert pitches(d, "Kick") == pitches(g, "Kick")
    assert [p - 5 for p in pitches(d, "Bass")] == pitches(g, "Bass")
    for p in pitches(g, "Bass"):
        assert 20 <= p <= 60


def test_swing_is_applied_to_the_odd_16ths_only():
    bp = C.create("house", swing_pct=58.0, seed=2)
    off = (0.58 - 0.5) * 0.5
    clips = {c["id"]: c for c in bp["clips"]}
    seen_odd = seen_even = 0
    for p in bp["placements"]:
        if p["stem"] != "Hats":
            continue
        for n in clips[p["clip"]]["notes"]:
            pos = (n["start"] % 4.0) * 4
            if abs(pos - round(pos)) < 1e-6:
                seen_even += 1
            else:
                assert abs((n["start"] % 0.5) - (0.25 + off)) < 1e-3
                seen_odd += 1
    assert seen_odd > 0 and seen_even > 0


def test_arrangement_comes_from_the_styles_own_template_and_short_caps_sections():
    names = {x["name"] for x in C.style_info("house")["sections"]}
    assert {s["label"] for s in C.create("house", seed=9)["sections"]} <= names      # only the template's own section kinds
    short = C.create("house", short=True, seed=9)
    assert max(s["length_bars"] for s in short["sections"]) <= 16


def test_intro_is_kick_only_in_techno_and_sections_never_overflow():
    bp = C.create("techno", seed=4)
    intro = bp["sections"][0]
    assert intro["active_stems"] == ["Kick"]
    for c in bp["clips"]:
        for n in c["notes"]:
            assert n["start"] + n["duration"] <= c["length_beats"] + 1e-6


def test_bad_inputs_and_out_of_range_tempo_are_explained():
    with pytest.raises(ValueError, match="unknown style"):
        C.create("polka")
    with pytest.raises(ValueError, match="unknown key"):
        C.create("techno", tonic="H")
    assert C.create("techno", bpm=170, seed=1)["warnings"]
    assert not C.create("techno", bpm=128, seed=1)["warnings"]


def test_the_library_json_is_in_sync_with_its_builder(tmp_path):
    from stemforge.styles import build_library
    fresh = build_library.build()
    shipped = json.loads(C.LIB_PATH.read_text())
    assert set(fresh["patterns"]) == set(shipped["patterns"])
    assert fresh["styles"].keys() == shipped["styles"].keys()
