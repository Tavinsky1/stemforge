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
    assert len(bp["sections"]) >= 6 and bp["global"]["tempo"] == C.style_info(style)["bpm"]["default"]


@pytest.mark.parametrize("style", C.STYLES)
def test_creation_is_deterministic_and_take_changes_the_alternatives(style):
    a, b = C.create(style, take=0), C.create(style, take=0)
    assert a["clips"] == b["clips"]
    c = C.create(style, take=1)
    # every style has more than one bass or chord alternative, so another take must differ somewhere
    assert a["clips"] != c["clips"]


def test_techno_bass_is_a_rolling_groove_that_leaves_the_kick_steps_free():
    bp = C.create("techno")
    g = bp["generation"]["checks"]
    assert g["bass_on_kick_steps_pct"] < 10                      # documented: the first 16th of every beat is left for the kick
    groove = [e for e in bp["generation"]["layers"] if e["layer"] == "bass" and e["pattern"] == "B14"]
    assert groove, "the rolling 16ths pattern is used in the groove sections"
    steps = sorted(set(_steps(bp, "Bass")))
    assert {1, 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15} <= set(steps)


def test_house_bass_answers_the_kick_on_the_offbeats():
    bp = C.create("house")
    g = bp["generation"]["checks"]
    assert g["bass_on_kick_steps_pct"] == 0.0
    assert g["bass_on_offbeat_8ths_pct"] >= 95
    assert set(_steps(bp, "Kick")) == {0, 4, 8, 12}
    assert set(_steps(bp, "Clap")) == {4, 12}


def test_downtempo_is_not_four_on_the_floor_and_cumbia_keeps_its_percussion():
    dt = C.create("downtempo")
    assert set(_steps(dt, "Kick")) != {0, 4, 8, 12}
    cu = C.create("electro_cumbia")
    assert "Perc" in {s["name"] for s in cu["stems"]}


def test_key_transposes_only_the_pitched_layers_and_drums_stay_put():
    d = C.create("techno", tonic="C")
    g = C.create("techno", tonic="G")                           # +7 -> written as -5 to stay in register
    def pitches(bp, stem):
        clips = {c["id"]: c for c in bp["clips"]}
        return sorted({n["pitch"] for p in bp["placements"] if p["stem"] == stem for n in clips[p["clip"]]["notes"]})
    assert pitches(d, "Kick") == pitches(g, "Kick")
    assert [p - 5 for p in pitches(d, "Bass")] == pitches(g, "Bass")
    for p in pitches(g, "Bass"):
        assert 20 <= p <= 60


def test_swing_is_applied_to_the_odd_16ths_only():
    bp = C.create("house", swing_pct=58.0)
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
    full = C.create("house")
    assert [s["length_bars"] for s in full["sections"]] == [x["bars"] for x in C.style_info("house")["sections"]]
    short = C.create("house", short=True)
    assert max(s["length_bars"] for s in short["sections"]) <= 16


def test_intro_is_kick_only_in_techno_and_sections_never_overflow():
    bp = C.create("techno")
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
    assert C.create("techno", bpm=170)["warnings"]
    assert not C.create("techno", bpm=128)["warnings"]


def test_the_library_json_is_in_sync_with_its_builder(tmp_path):
    from stemforge.styles import build_library
    fresh = build_library.build()
    shipped = json.loads(C.LIB_PATH.read_text())
    assert set(fresh["patterns"]) == set(shipped["patterns"])
    assert fresh["styles"].keys() == shipped["styles"].keys()
