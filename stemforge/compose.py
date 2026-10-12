"""Write NEW Keys and Synth parts from the idea of a song (see idea.py). Deterministic for a given seed.

What is kept from the audio (measured, never guessed): tempo, section map and which layers are active, where each
layer really hits (16-step weights), how hard, how busy, the swing, the drone key and the colour tones of each section,
and the bass root of every bar. What is written here: the notes. Everything generated is labelled source="generated".

The rules below come from the owner's NotebookLM base (knowledge/HYPNOTIC_TECHNO_NOTEBOOKLM_KNOWLEDGE_BASE.md,
research/arrangement_conventions.md, arrangement/arrangement_rules.json) and from published production practice. They are
listed in RULES so the app can show them. They are rules about structure and dynamics; whether the result is beautiful
is for ears to decide.
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

# three-tier velocity hierarchy (NotebookLM base, section 5): strong 100-110, medium 75-85, subtle 50-65, plus ghosts
TIERS = {"strong": (105.0, 4.0), "medium": (80.0, 4.0), "subtle": (59.0, 5.0), "ghost": (47.0, 4.0)}
VEL_CEILING = 112    # the base's "strong" tier is 100-110; leave a little room for the swell
VEL_LANE = ["strong", "subtle", "medium", "subtle", "ghost", "medium", "subtle"]

RULES = [
    "Pitch is limited to the song's own palette: drone, open fifth, one colour tone at a time, never a major third.",
    "The synth uses at most 3 pitch classes at a time (restraint creates gravity).",
    "Pitch lane and velocity lane have different lengths (3/5/7 against 5/7), so the pattern phases for 35+ steps.",
    "Three velocity tiers: strong 100-110, medium 75-85, subtle 50-65, with ghosts; never flat.",
    "Swing and micro-timing on the 16ths use the song's measured swing; hits on the beat stay on the grid.",
    "Keys and Synth interlock: they do not hit the same step in a section.",
    "Chord stabs leave a gap (no neighbouring 16ths) outside peaks so a dotted-eighth delay has room.",
    "Keys and Synth stay out of the bass register; the bass is never touched.",
    "One new element per 4-bar phrase: if both layers would enter together, the synth waits 4 bars.",
    "Strip back before a drop: the last 2 bars before a bigger section lose the synth and thin the keys.",
    "The outro mirrors the intro: the synth thins out, then leaves; the keys end on the bare drone.",
    "Layers enter and leave exactly where the source audio's layers do; nothing is added to the song's arc "
    "except a soft D+A bed in the last 4 bars of the intro (optional).",
]


def _rng(seed: int, *tag) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(("%d:%s" % (seed, ":".join(map(str, tag)))).encode()))


def _clamp(v: float, lo: int = 1, hi: int = 127) -> int:
    return int(max(lo, min(hi, round(v))))


def keys_colour_pitch(semi: int) -> int:
    """Colour tone in the keys register (D3..G4): the low colours (b7, leading tone) sit under the tonic."""
    return TONIC_KEYS + semi if semi >= 10 else TONIC_KEYS + 12 + semi


def synth_colour_pitch(semi: int) -> int:
    return TONIC_SYNTH + semi - (12 if semi >= 10 else 0)


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


def _pick_steps(weights: list[float], n: int, forbidden: set, rng, jitter: float = 0.15, min_gap: int = 1) -> list[int]:
    w = np.asarray(weights, float) + rng.random(16) * jitter * max(max(weights), 1e-6)
    chosen: list[int] = []
    for i in (int(x) for x in np.argsort(-w)):
        if i in forbidden or any(abs(i - c) < min_gap for c in chosen):
            continue
        chosen.append(i)
        if len(chosen) == n:
            break
    return sorted(chosen)


def _swell(bar: int, amp: float) -> float:
    return amp * 0.5 * (1 + np.sin(2 * np.pi * bar / 8.0)) - amp * 0.25


def _gain(energy_db: float) -> float:
    """Quiet sections a little softer, the peak a little firmer (peak = denser, not much louder)."""
    return float(np.clip(0.88 + 0.025 * (energy_db + 9.0), 0.82, 1.06))


def _vel(tier: str, rng, gain: float, extra: float = 0.0) -> int:
    centre, spread = TIERS[tier]
    return _clamp(centre * gain + extra + rng.normal(0, spread * 0.6), hi=VEL_CEILING)


def _step_tier(st: int) -> str:
    return "strong" if st % 4 == 0 else ("medium" if st % 4 == 2 else "subtle")


def _keys_section(sec: dict, layer: dict, tonic_pc: int, roots: list, swing: float, seed: int, ctx: dict) -> tuple[list, set]:
    notes: list[dict] = []
    used: set = set()
    rng = _rng(seed, "keys", sec["index"])
    colour = _colour_for(layer["chroma"], tonic_pc)
    gain = _gain(sec["energy_db"])
    n_bars = sec["length_bars"]
    base_n = int(np.clip(round(layer["onsets_per_bar"] * 0.45), 2, 7))
    sustained = sec["role"] in ("breakdown", "outro")
    peak = sec["role"] == "peak"
    pattern: list[int] = []
    for b in range(n_bars):
        if b % 4 == 0:   # new 4-bar cell, mutated from the last one by at most one hit
            blk = _rng(seed, "keysblk", sec["index"], b // 4)
            n = int(np.clip(base_n + int(blk.integers(-1, 2)), 2, 7))
            pattern = _pick_steps(layer["step_weights"], n, set(), blk, 0.12, min_gap=1 if peak else 2)
        shift = _bar_root(roots, b)
        root = TONIC_KEYS + shift                                               # D3 (or F3 / G3 when the bass moves)
        fifth, top = root + 7, root + 12
        use_colour = (colour is not None and shift == 0 and (b % 4 == 3 or sec["role"] in ("build", "peak")))
        voicing = [root, fifth, keys_colour_pitch(colour)] if use_colour else [root, fifth, top]
        bare_drone = sec["role"] == "outro" and b >= n_bars - 8                # the outro ends on D+A only
        if bare_drone:
            voicing = [root, fifth]
        if sustained:
            fade = 20.0 * b / max(n_bars, 1) if sec["role"] == "outro" else 0.0
            for p in voicing:
                notes.append({"pitch": p, "start": b * BEAT_BAR + 0.0, "duration": 3.84 if sec["role"] == "outro" else 1.92,
                              "velocity": _vel("subtle", rng, gain, 4 - fade + _swell(b, 8)), "confidence": 1.0,
                              "source": "generated"})
            continue
        steps = list(pattern)
        if b % 4 == 3 and len(steps) > 2 and rng.random() < 0.55:
            steps.pop(int(rng.integers(0, len(steps))))                         # the breath before the cell turns over
        if b % 8 == 7 and 15 not in steps and not any(abs(15 - s) < 2 for s in steps):
            steps.append(15)                                                    # pickup into the next 8-bar block
        if ctx.get("pre_drop") and b >= n_bars - 2:
            steps = [0]                                                         # strip back before the drop
        steps = sorted(set(steps))
        used |= set(steps)
        # the hierarchy follows each hit's importance in this song (its measured weight), with the beat as a tie-breaker:
        # the main stabs are strong/medium even when they sit on the 16th "e"
        order = sorted(steps, key=lambda x: -layer["step_weights"][x])
        rank = {x: i for i, x in enumerate(order)}
        for k, st in enumerate(steps):
            r = rank[st] / max(len(order) - 1, 1)
            tier = "strong" if r < 0.3 else ("medium" if r < 0.72 else "subtle")
            if st % 4 == 0 and tier == "medium":
                tier = "strong"
            if st % 4 == 3 and tier == "subtle" and rng.random() < 0.5:
                tier = "ghost"
            vel = _vel(tier, rng, gain, _swell(b, 10) + (4 if k == len(steps) - 1 else 0))
            dur = 0.22 + 0.18 * (st % 4 == 1) + (0.35 if k == len(steps) - 1 else 0.0)
            micro = float(rng.normal(0, 0.006)) if st % 4 else 0.0              # the grid hits stay on the grid
            start = b * BEAT_BAR + st * 0.25 + micro
            for j, p in enumerate(voicing):
                notes.append({"pitch": p, "start": round(max(start + j * 0.004, 0.0), 4), "duration": round(dur, 3),
                              "velocity": _clamp(vel - j * 3 + rng.normal(0, 2), hi=VEL_CEILING), "confidence": 1.0,
                              "source": "generated"})
    return apply_swing(notes, swing), used


def _synth_section(sec: dict, layer: dict, tonic_pc: int, keys_steps: set, swing: float, seed: int,
                   lanes: dict, ctx: dict) -> list:
    notes: list[dict] = []
    rng = _rng(seed, "synth", sec["index"])
    colour = _colour_for(layer["chroma"], tonic_pc)
    gain = _gain(sec["energy_db"])
    n_bars = sec["length_bars"]
    c_tone = synth_colour_pitch(colour if colour is not None else 1)           # Eb when the section shows no colour
    peak = sec["role"] in ("peak", "build") or sec["energy_db"] > -3.5
    quiet = sec["role"] in ("breakdown", "outro")
    # at most three pitch classes (D, A, one colour): the cell only re-orders and re-registers them
    if quiet:
        cell = [74, 69, 74]
    elif peak:
        cell = [74, 69, 74, c_tone, 69, 62, 74]
    else:
        cell = [74, 69, 74, c_tone, 69]
    vlen = 5 if len(cell) == 7 else 7                                           # coprime with the pitch lane
    vel_lane = [VEL_LANE[i % len(VEL_LANE)] for i in range(vlen)]
    n_hits = int(np.clip(round(layer["onsets_per_bar"] * (0.55 if peak else 0.4)), 1, 9))
    start_bar = int(ctx.get("enter_delay_bars", 0))
    for b in range(start_bar, n_bars):
        if ctx.get("pre_drop") and b >= n_bars - 2:
            continue                                                            # strip back before the drop
        if sec["role"] == "outro":
            if b >= n_bars - 8:
                continue                                                        # mirror of the intro: the synth leaves first
            thinned = n_hits - int(b // 8)
        else:
            thinned = n_hits
        blk = _rng(seed, "synthblk", sec["index"], b // 4)
        k = int(np.clip(thinned + int(blk.integers(-1, 2)), 1, 9))
        steps = _pick_steps(layer["step_weights"], k, keys_steps, blk, 0.2)
        if quiet:
            steps = steps[: max(1, k // 2)]
        for i, st in enumerate(steps):
            pitch = cell[lanes["p"] % len(cell)]
            tier = vel_lane[lanes["v"] % len(vel_lane)]
            lanes["p"] += 1
            lanes["v"] += 1
            vel = _vel(tier, rng, gain * 0.95, _swell(b, 8))
            dur = (0.8 if quiet else 0.2) + 0.12 * (i % 2)
            micro = float(rng.normal(0, 0.009)) if st % 4 else 0.0
            notes.append({"pitch": int(np.clip(pitch, *SYNTH_RANGE)),
                          "start": round(max(b * BEAT_BAR + st * 0.25 + micro, 0.0), 4),
                          "duration": round(dur, 3), "velocity": vel, "confidence": 1.0, "source": "generated"})
    return apply_swing(notes, swing)


def _intro_bed(sec: dict, seed: int) -> list:
    """The last 4 bars of the intro: a bare D+A fifth fading in, so the first groove entrance has something to land on."""
    rng = _rng(seed, "bed")
    notes = []
    for b in range(max(sec["length_bars"] - 4, 0), sec["length_bars"]):
        v = 34 + 9 * (b - (sec["length_bars"] - 4)) + rng.normal(0, 2)
        for p in (TONIC_KEYS, TONIC_KEYS + 7):
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


def _layer(idea: dict, stem: str, index: int) -> dict:
    lay = idea["layers"][stem]
    return lay[str(index)] if str(index) in lay else lay[index]


def compose(bp: dict, idea: dict, seed: int = 0, swing_pct: float | None = None, intro_bed: bool = True) -> dict:
    """A new blueprint: Drums/Bass/Percussion as transcribed (re-swung), Keys and Synth newly written."""
    out = copy.deepcopy(bp)
    swing = idea["groove"]["swing_pct"] if swing_pct is None else swing_pct
    tonic_pc = idea["key"]["tonic_pc"]
    # transcribed stems that stay: everything rhythmic (drum-mode stems, whatever they are called) and the mono bass
    keep_stems = [s for s in bp["stems"] if s.get("mode") == "drums" or s["role"] == "bass"]
    drum_names = {s["name"] for s in keep_stems if s.get("mode") == "drums"}
    keep_names = {s["name"] for s in keep_stems}
    key_src = next((n for n, r in idea["roles"].items() if r == "keys"), None)
    syn_src = next((n for n, r in idea["roles"].items() if r == "synth"), None)
    if key_src is None and syn_src is None:
        raise ValueError("this song has no stem labelled Keys or Synth, so there is nothing to write. "
                         "Label a stem as Keys or Synth in step 1 and analyze again")
    secs = idea["sections"]
    clips, placements = [], []
    clip_by_id = {c["id"]: c for c in bp["clips"]}
    # 1) transcribed stems keep their notes; only the 16ths of drums/percussion are re-swung to the measured groove
    for p in bp["placements"]:
        if p["stem"] not in keep_names:
            continue
        c = clip_by_id[p["clip"]]
        nid = "%s|%d" % (p["stem"], p["section"])
        clips.append({**copy.deepcopy(c), "id": nid,
                      "notes": apply_swing(c["notes"], swing) if p["stem"] in drum_names else c["notes"],
                      "used_in": [p["section"]]})
        placements.append({"stem": p["stem"], "section": p["section"], "clip": nid})

    # 2) arrangement context for the generated layers
    def ctx_for(i: int, stem: str) -> dict:
        s = secs[i]
        nxt = secs[i + 1] if i + 1 < len(secs) else None
        prev = secs[i - 1] if i > 0 else None
        pre_drop = bool(nxt and s["length_bars"] >= 4 and (nxt["role"] == "peak" or nxt["energy_db"] - s["energy_db"] >= 1.5))
        both_new = (prev is None or (key_src not in prev["active_stems"] and syn_src not in prev["active_stems"]))
        delay = 4 if (stem == syn_src and both_new and key_src in s["active_stems"] and s["length_bars"] >= 8) else 0
        return {"pre_drop": pre_drop, "enter_delay_bars": delay}

    keys_steps: dict[int, set] = {}
    for s in secs:
        notes = []
        if key_src and key_src in s["active_stems"]:
            notes, used = _keys_section({**s}, _layer(idea, key_src, s["index"]), tonic_pc, s["bass_roots_by_bar"], swing,
                                        seed, ctx_for(s["index"], key_src))
            keys_steps[s["index"]] = used
        elif intro_bed and s["role"] == "intro":
            notes = _intro_bed(s, seed)
        if notes:
            cid = "%s|%d" % (KEYS, s["index"])
            clips.append({"id": cid, "stem": KEYS, "name": "%s %s" % (KEYS, s["label"]), "length_beats": s["length_bars"] * BEAT_BAR,
                          "notes": notes, "loop_period_bars": None, "used_in": [s["index"]]})
            placements.append({"stem": KEYS, "section": s["index"], "clip": cid})
    lanes = {"p": 0, "v": 0}          # never reset between sections: the phasing carries through the whole song
    for s in secs:
        if not syn_src or syn_src not in s["active_stems"]:
            continue
        notes = _synth_section({**s}, _layer(idea, syn_src, s["index"]), tonic_pc, keys_steps.get(s["index"], set()),
                               swing, seed, lanes, ctx_for(s["index"], syn_src))
        if notes:
            cid = "%s|%d" % (SYNTH, s["index"])
            clips.append({"id": cid, "stem": SYNTH, "name": "%s %s" % (SYNTH, s["label"]),
                          "length_beats": s["length_bars"] * BEAT_BAR, "notes": notes, "loop_period_bars": None,
                          "used_in": [s["index"]]})
            placements.append({"stem": SYNTH, "section": s["index"], "clip": cid})
    stems = [copy.deepcopy(s) for s in keep_stems]
    for name, role in ((KEYS, "keys"), (SYNTH, "synth")):
        if not any(c["stem"] == name for c in clips):
            continue
        stems.append({"name": name, "role": role, "path": None, "mode": "poly",
                      "transcription": {"backend": "stemforge.compose/2 seed=%d" % seed, "skipped": False, "reason": None,
                                        "warnings": [], "source": "generated", "stats": {}}})
    _finalize(clips)
    out["stems"], out["clips"], out["placements"] = stems, clips, placements
    out["song"] = {**out["song"], "name": out["song"]["name"] + " (generated)"}
    out["generation"] = {"seed": seed, "swing_pct": swing, "from_idea": idea.get("schema"), "rules": RULES,
                         "kept_transcribed": [s["name"] for s in keep_stems], "generated": list(GENERATED)}
    return out


def report(gen: dict, idea: dict) -> dict:
    """Numbers that say whether the rules held. Nothing here judges the music; it checks the rules."""
    tonic = idea["key"]["tonic_pc"]
    allowed = {(tonic + x) % 12 for x in (0, 7)} | {(tonic + s) % 12 for s in COLOUR}
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
        per_clip_pcs = [len({n["pitch"] % 12 for n in c["notes"]}) for c in cl if c["notes"]]
        tiers = {"strong (98+)": int((v >= 98).sum()), "medium (70-97)": int(((v >= 70) & (v < 98)).sum()),
                 "subtle/ghost (<70)": int((v < 70).sum())}
        rows[name] = {"clips": len(cl), "notes": len(notes), "notes_per_bar": round(len(notes) / max(bars, 1), 1),
                      "velocity_min_max": [int(v.min()), int(v.max())], "velocity_std": round(float(v.std()), 1),
                      "distinct_velocities": int(len(set(v.tolist()))), "velocity_tiers": tiers,
                      "pitch_range": [int(p.min()), int(p.max())],
                      "pitch_classes": sorted({PC_NAMES[int(x) % 12] for x in p}),
                      "max_pitch_classes_in_a_clip": int(max(per_clip_pcs)),
                      "outside_palette": int(sum(1 for x in p if int(x) % 12 not in allowed)),
                      "off_grid_pct": round(float((grid > 0.01).mean() * 100), 1)}
    return rows


def plain_report(rep: dict) -> list[str]:
    """The same numbers in plain English for the app."""
    out = []
    for name, r in rep.items():
        out.append("%s: %d notes in %d clips (%.1f per bar). Velocities %d-%d, %d different values. Pitches %s. "
                   "%d notes outside the song's palette. Swing/micro-timing on %.0f%% of notes."
                   % (name, r["notes"], r["clips"], r["notes_per_bar"], *r["velocity_min_max"], r["distinct_velocities"],
                      ", ".join(r["pitch_classes"]), r["outside_palette"], r["off_grid_pct"]))
    return out
