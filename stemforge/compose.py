"""Write NEW Keys and Synth parts from the idea of a song (see idea.py). Deterministic for a given seed.

What is kept from the audio (measured, never guessed): tempo, section map and which layers are active, where each
layer really hits (16-step weights), how hard, how busy, the swing, the drone key and the colour tones of each section,
and the bass root of every bar. What is written here: the notes. Everything generated is labelled source="generated".

Taste rules (the same ones a producer applies by ear):
- no flat velocities: downbeat accents, ghost notes, a slow 8-bar swell, small random jitter
- swing and micro-timing on the 16ths, measured from the song
- pitch is constrained to the song's palette: drone, open fifth, one colour tone at a time (Eb/C/G/E), never a major third
- keys and synth interlock (they do not hit the same step), and keep out of the bass register
- hypnotic repetition with micro-shifts: patterns stay for 4 bars and mutate by one hit; the synth pitch cell (5 or 7
  notes) cycles against the 16-step rhythm so it phases instead of looping
- the arc is the song's own: layers enter and leave where the audio says; breakdown and outro hold and thin out
"""
from __future__ import annotations

import copy
import zlib

import numpy as np

from .idea import PC_NAMES

BEAT_BAR = 4
KEYS, SYNTH = "G Keys", "G Synth"
KEYS_RANGE, SYNTH_RANGE = (48, 70), (62, 88)
GENERATED = (KEYS, SYNTH)
# colour tones allowed on top of the D drone, in semitones from the tonic. No major third, no major sixth, no tritone.
COLOUR = {1: "b2", 10: "b7", 5: "4", 3: "b3", 2: "9", 11: "leading"}
TONIC_KEYS = 50      # D3: keys voicings are built up from here
TONIC_SYNTH = 74     # D5: the synth cell lives around here


def keys_colour_pitch(semi: int) -> int:
    """Colour tone in the keys register (D3..G4): the low colours (b7, leading tone) sit under the tonic."""
    return TONIC_KEYS + semi if semi >= 10 else TONIC_KEYS + 12 + semi


def synth_colour_pitch(semi: int) -> int:
    return TONIC_SYNTH + semi - (12 if semi >= 10 else 0)


def _rng(seed: int, *tag) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(("%d:%s" % (seed, ":".join(map(str, tag)))).encode()))


def _clamp(v: float, lo: int = 1, hi: int = 127) -> int:
    return int(max(lo, min(hi, round(v))))


def swing_offset(swing_pct: float) -> float:
    """Beats by which the 'e' and 'a' 16ths are delayed for a swing percentage (50 = none)."""
    return max(0.0, (swing_pct / 100.0 - 0.5) * 0.5)


def apply_swing(notes: list[dict], swing_pct: float) -> list[dict]:
    off = swing_offset(swing_pct)
    out = []
    for n in notes:
        step = n["start"] * 4
        odd = abs(step - round(step)) < 1e-3 and int(round(step)) % 2 == 1
        out.append({**n, "start": round(n["start"] + off, 4)} if odd and off else dict(n))
    return out


def _colour_for(section_chroma: list[float], tonic_pc: int) -> int | None:
    """Semitones above the tonic of the strongest allowed colour tone in this section, or None."""
    best, best_w = None, 0.07
    for semi in COLOUR:
        w = section_chroma[(tonic_pc + semi) % 12]
        if w > best_w:
            best, best_w = semi, w
    return best


def _bar_root(roots: list, b: int) -> int:
    """Semitones above the tonic of the bass root of bar b (0 when unknown or outside our vocabulary)."""
    return 0 if b >= len(roots) or roots[b] is None else {"F": 3, "G": 5}.get(roots[b], 0)


def _pick_steps(weights: list[float], n: int, forbidden: set, rng, jitter: float = 0.15) -> list[int]:
    w = np.asarray(weights, float) + rng.random(16) * jitter * max(max(weights), 1e-6)
    order = [int(i) for i in np.argsort(-w) if int(i) not in forbidden]
    return sorted(order[:n])


def _swell(bar: int, amp: float) -> float:
    return amp * 0.5 * (1 + np.sin(2 * np.pi * bar / 8.0))


def _keys_section(sec: dict, layer: dict, tonic_pc: int, roots: list, swing: float, seed: int, role_fade: bool) -> tuple[list, set]:
    notes: list[dict] = []
    used_by_bar: dict[int, set] = {}
    rng = _rng(seed, "keys", sec["index"])
    colour = _colour_for(layer["chroma"], tonic_pc)
    base_n = int(np.clip(round(layer["onsets_per_bar"] * 0.45), 2, 7))
    sustained = sec["role"] in ("breakdown", "outro")
    pattern: list[int] = []
    for b in range(sec["length_bars"]):
        if b % 4 == 0:   # new 4-bar cell, mutated from the last one by at most one hit
            blk = _rng(seed, "keysblk", sec["index"], b // 4)
            n = int(np.clip(base_n + int(blk.integers(-1, 2)), 2, 7))
            pattern = _pick_steps(layer["step_weights"], n, set(), blk, 0.12)
        steps = list(pattern)
        if b % 4 == 3 and len(steps) > 2 and rng.random() < 0.55:
            steps.pop(int(rng.integers(0, len(steps))))                         # the "breath" before the cell turns over
        if b % 8 == 7 and 15 not in steps:
            steps.append(15)                                                    # pickup into the next 8-bar block
        steps = sorted(set(steps))
        shift = _bar_root(roots, b)
        root = 50 + shift                                                       # D3 (or F3 / G3 when the bass moves)
        fifth = root + 7
        top = root + 12
        use_colour = (colour is not None and shift == 0                      # colour is relative to D: skip it over F/G
                      and (b % 4 == 3 or sec["role"] in ("build", "peak")))
        if use_colour:
            voicing = [root, fifth, keys_colour_pitch(colour)]                # no D4 next to the colour: keep the rub clean
        else:
            voicing = [root, fifth, top]
        if sustained:
            hold = 4.0 if sec["role"] == "outro" else 2.0
            if b % int(hold // 4 or 1) == 0 or hold == 4.0:
                vel = 62 - (22 * b / max(sec["length_bars"], 1) if role_fade else 0) + _swell(b, 8)
                for p in voicing:
                    notes.append({"pitch": p, "start": b * BEAT_BAR + 0.0, "duration": hold * 0.96,
                                  "velocity": _clamp(vel + rng.normal(0, 3)), "confidence": 1.0, "source": "generated"})
            continue
        used_by_bar[b] = set(steps)
        for k, st in enumerate(steps):
            accent = 1.0 if st % 4 == 0 else (0.80 if st % 2 == 1 else 0.68)
            vel = 66 + 36 * accent * layer["mean_strength"] + _swell(b, 12) + rng.normal(0, 4)
            if k == len(steps) - 1:
                vel += 6
            ghost = st % 4 == 3 and rng.random() < 0.5
            if ghost:
                vel = 44 + rng.normal(0, 4)
            dur = 0.22 + 0.18 * (st % 4 == 1) + (0.35 if k == len(steps) - 1 else 0.0)
            micro = float(rng.normal(0, 0.006)) if st % 4 else 0.0
            start = b * BEAT_BAR + st * 0.25 + micro
            for j, p in enumerate(voicing):
                notes.append({"pitch": p, "start": round(max(start + j * 0.004, 0.0), 4), "duration": round(dur, 3),
                              "velocity": _clamp(vel - j * 3 + rng.normal(0, 2)), "confidence": 1.0, "source": "generated"})
    return apply_swing(notes, swing), set().union(*used_by_bar.values()) if used_by_bar else set()


def _synth_section(sec: dict, layer: dict, tonic_pc: int, roots: list, keys_steps: dict, swing: float, seed: int,
                   cycle_state: dict) -> list:
    notes: list[dict] = []
    rng = _rng(seed, "synth", sec["index"])
    colour = _colour_for(layer["chroma"], tonic_pc)
    c_tone = synth_colour_pitch(colour if colour is not None else 1)       # Eb when the section shows no colour
    peak = sec["role"] in ("peak", "build") or sec["energy_db"] > -3.5
    quiet = sec["role"] in ("breakdown", "outro")
    low_colour = synth_colour_pitch(5 if colour != 5 else 10)               # G4 (or C5): a lower answer inside the cell
    cell = ([74, 69, 74, c_tone, 69, low_colour, 86] if peak else [74, 69, 74, c_tone, 69])
    if quiet:
        cell = [74, 69, 74]
    n_hits = int(np.clip(round(layer["onsets_per_bar"] * (0.55 if peak else 0.4)), 1, 9))
    for b in range(sec["length_bars"]):
        blk = _rng(seed, "synthblk", sec["index"], b // 4)
        taken = keys_steps.get(sec["index"], set())
        k = int(np.clip(n_hits + int(blk.integers(-1, 2)), 1, 9))
        steps = _pick_steps(layer["step_weights"], k, taken, blk, 0.2)
        if quiet:
            steps = steps[: max(1, k // 2)]
        for i, st in enumerate(steps):
            pitch = cell[cycle_state["i"] % len(cell)]
            cycle_state["i"] += 1
            first = cycle_state["i"] % len(cell) == 1
            vel = 62 + 30 * layer["mean_strength"] * (1.0 if st % 4 == 0 else 0.8) + _swell(b, 10) + rng.normal(0, 5)
            if first:
                vel += 14
            if rng.random() < 0.18:
                vel = 46 + rng.normal(0, 4)                                   # ghost
            dur = (0.8 if quiet else 0.2) + 0.12 * (i % 2)
            micro = float(rng.normal(0, 0.009))
            notes.append({"pitch": int(np.clip(pitch, *SYNTH_RANGE)), "start": round(max(b * BEAT_BAR + st * 0.25 + micro, 0.0), 4),
                          "duration": round(dur, 3), "velocity": _clamp(vel), "confidence": 1.0, "source": "generated"})
    return apply_swing(notes, swing)


def _intro_bed(sec: dict, seed: int) -> list:
    """The last 4 bars of the intro: a bare D+A fifth fading in, so the first groove entrance has something to land on."""
    rng = _rng(seed, "bed")
    notes = []
    for b in range(max(sec["length_bars"] - 4, 0), sec["length_bars"]):
        v = 34 + 9 * (b - (sec["length_bars"] - 4)) + rng.normal(0, 2)
        for p in (50, 57):
            notes.append({"pitch": p, "start": b * BEAT_BAR, "duration": 3.9, "velocity": _clamp(v), "confidence": 1.0,
                          "source": "generated"})
    return notes


def _finalize(clips: list[dict]) -> None:
    """Keep every note inside its clip: swing and pickups can push the last step past the end."""
    for c in clips:
        end, kept = float(c["length_beats"]), []
        for n in c["notes"]:
            if n["start"] >= end - 1e-6:
                continue
            d = min(n["duration"], end - n["start"])
            if d < 0.04:
                continue
            kept.append({**n, "duration": round(d, 4)})
        c["notes"] = sorted(kept, key=lambda n: (n["start"], n["pitch"]))


def compose(bp: dict, idea: dict, seed: int = 0, swing_pct: float | None = None, intro_bed: bool = True) -> dict:
    """A new blueprint: Drums/Bass/Percussion as transcribed (re-swung), Keys and Synth newly written."""
    out = copy.deepcopy(bp)
    swing = idea["groove"]["swing_pct"] if swing_pct is None else swing_pct
    tonic_pc = idea["key"]["tonic_pc"]
    keep_stems = [s for s in bp["stems"] if s["role"] in ("drums", "bass")]
    key_src = next(n for n, r in idea["roles"].items() if r == "keys")
    syn_src = next(n for n, r in idea["roles"].items() if r == "synth")
    secs = {s["index"]: s for s in idea["sections"]}
    clips, placements = [], []
    clip_by_id = {c["id"]: c for c in bp["clips"]}
    # 1) transcribed stems keep their notes; only the 16ths are re-swung to the measured groove
    for p in bp["placements"]:
        if p["stem"] not in {s["name"] for s in keep_stems}:
            continue
        c = clip_by_id[p["clip"]]
        role = idea["roles"][p["stem"]]
        nid = "%s|%d" % (p["stem"], p["section"])
        clips.append({**copy.deepcopy(c), "id": nid, "notes": apply_swing(c["notes"], swing) if role == "drums" else c["notes"],
                      "used_in": [p["section"]]})
        placements.append({"stem": p["stem"], "section": p["section"], "clip": nid})
    # 2) generated parts
    keys_steps: dict[int, set] = {}
    cycle = {"i": 0}
    for s in idea["sections"]:
        active = set(s["active_stems"])
        sec = {**s}
        if key_src in active:
            notes, used = _keys_section(sec, idea["layers"][key_src][str(s["index"])] if str(s["index"]) in idea["layers"][key_src]
                                        else idea["layers"][key_src][s["index"]], tonic_pc, s["bass_roots_by_bar"], swing, seed,
                                        role_fade=(s["role"] == "outro"))
            keys_steps[s["index"]] = used
        elif intro_bed and s["role"] == "intro":
            notes = _intro_bed(sec, seed)
        else:
            notes = []
        if notes:
            cid = "%s|%d" % (KEYS, s["index"])
            clips.append({"id": cid, "stem": KEYS, "name": "%s %s" % (KEYS, s["label"]), "length_beats": s["length_bars"] * BEAT_BAR,
                          "notes": notes, "loop_period_bars": None, "used_in": [s["index"]]})
            placements.append({"stem": KEYS, "section": s["index"], "clip": cid})
    for s in idea["sections"]:
        if syn_src not in set(s["active_stems"]):
            continue
        lay = idea["layers"][syn_src]
        layer = lay[str(s["index"])] if str(s["index"]) in lay else lay[s["index"]]
        notes = _synth_section({**s}, layer, tonic_pc, s["bass_roots_by_bar"], keys_steps, swing, seed, cycle)
        if notes:
            cid = "%s|%d" % (SYNTH, s["index"])
            clips.append({"id": cid, "stem": SYNTH, "name": "%s %s" % (SYNTH, s["label"]),
                          "length_beats": s["length_bars"] * BEAT_BAR, "notes": notes, "loop_period_bars": None,
                          "used_in": [s["index"]]})
            placements.append({"stem": SYNTH, "section": s["index"], "clip": cid})
    stems = [copy.deepcopy(s) for s in keep_stems]
    for name, role in ((KEYS, "keys"), (SYNTH, "synth")):
        stems.append({"name": name, "role": role, "path": None, "mode": "poly",
                      "transcription": {"backend": "stemforge.compose/1 seed=%d" % seed, "skipped": False, "reason": None,
                                        "warnings": [], "source": "generated", "stats": {}}})
    _finalize(clips)
    out["stems"], out["clips"], out["placements"] = stems, clips, placements
    out["song"] = {**out["song"], "name": out["song"]["name"] + " (generated)"}
    out["generation"] = {"seed": seed, "swing_pct": swing, "from_idea": idea.get("schema"),
                         "kept_transcribed": [s["name"] for s in keep_stems], "generated": list(GENERATED)}
    return out


def report(gen: dict, idea: dict) -> dict:
    """Numbers that say whether the taste rules held. Nothing here judges the music; it checks the rules."""
    tonic = idea["key"]["tonic_pc"]
    allowed = {(tonic + x) % 12 for x in (0, 7, 12) } | {(tonic + s) % 12 for s in COLOUR} | {(tonic + 3) % 12, (tonic + 5) % 12}
    rows = {}
    for name in GENERATED:
        cl = [c for c in gen["clips"] if c["stem"] == name]
        notes = [n for c in cl for n in c["notes"]]
        if not notes:
            continue
        v = np.array([n["velocity"] for n in notes])
        p = np.array([n["pitch"] for n in notes])
        grid = np.array([abs(n["start"] * 4 - round(n["start"] * 4)) for n in notes])
        bars = sum(c["length_beats"] / BEAT_BAR for c in cl)
        rows[name] = {"clips": len(cl), "notes": len(notes), "notes_per_bar": round(len(notes) / max(bars, 1), 1),
                      "velocity_min_max": [int(v.min()), int(v.max())], "velocity_std": round(float(v.std()), 1),
                      "distinct_velocities": int(len(set(v.tolist()))),
                      "pitch_range": [int(p.min()), int(p.max())],
                      "pitch_classes": sorted({PC_NAMES[int(x) % 12] for x in p}),
                      "outside_palette": int(sum(1 for x in p if int(x) % 12 not in allowed)),
                      "off_grid_pct": round(float((grid > 0.01).mean() * 100), 1)}
    return rows
