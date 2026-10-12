"""Create a song skeleton from zero in one of four styles. Every song is different; none contains an invented note.

Everything written comes from the style library (library/styles.json): patterns from the owner's NotebookLM research,
bar patterns measured from real loops, and documented recipes, each with its source. The arrangement is the style's own
(knowledge/arrangement/*.json). This module only ASSEMBLES: it picks, for every section, the pattern its energy and
elements call for, tiles it over the bars, transposes pitched parts to the key, and applies the style's swing.

Variety comes from a SEED. The seed decides, from sourced material only: the key and tempo (inside the style's range),
the swing (inside the style's range), the section lengths and whether the peak comes back after a second breakdown (in
8-bar steps, the rule from the owner's arrangement research), which of the library's alternatives each layer uses and
how they alternate between sections, which optional layers sit out a section, and which fill closes a section.
The same seed always gives the same song, so a song you like can be recreated from its number.
"""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

from ..compose import apply_swing

BEATS_PER_BAR = 4
LIB_PATH = Path(__file__).resolve().parent / "library" / "styles.json"
STYLES = ("techno", "house", "downtempo", "electro_cumbia")
TONICS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# layer -> (track name, role, mode). Drum-mode layers are never transposed.
LAYERS = {
    "kick": ("Kick", "kick", "drums"), "clap": ("Clap", "snare", "drums"), "hat": ("Hats", "hat", "drums"),
    "perc": ("Perc", "perc", "drums"), "bass": ("Bass", "bass", "mono"), "chords": ("Chords", "keys", "poly"),
    "pad": ("Pad", "pad", "poly"), "lead": ("Lead", "synth", "poly"),
}
ORDER = ["kick", "clap", "hat", "perc", "bass", "chords", "pad", "lead"]
PITCHED = {"bass", "chords", "pad", "lead"}
ELEMENT_ALIAS = {"hats": "hat", "percussion": "perc", "claps": "clap", "snare": "clap"}


@lru_cache(maxsize=1)
def library() -> dict:
    return json.loads(LIB_PATH.read_text())


def style_info(style: str) -> dict:
    s = library()["styles"][style]
    return {"label": s["label"], "bpm": s["bpm"], "tonic": s["tonic"], "swing_pct": s["swing_pct"], "refs": s["refs"],
            "sections": [{"name": x["name"], "bars": x["bars"], "energy": x["energy"], "elements": x["elements"]}
                         for x in s["arrangement"]]}


def _shift(tonic: str) -> int:
    pc = TONICS.index(tonic)
    return pc if pc <= 6 else pc - 12          # keep every pitched part within a tritone of where it was written (C)


def _tile(pattern: dict, n_bars: int, shift: int = 0) -> list[dict]:
    """Section-relative notes: the pattern repeated for n_bars."""
    L = int(pattern["bars"])
    out = []
    for b in range(n_bars):
        k = b % L
        for n in pattern["notes"]:
            if k * BEATS_PER_BAR <= n["start"] < (k + 1) * BEATS_PER_BAR:
                p = n["pitch"] + shift
                out.append({"pitch": int(min(127, max(0, p))), "start": b * BEATS_PER_BAR + (n["start"] - k * BEATS_PER_BAR),
                            "duration": max(0.05, float(n["dur"])), "velocity": int(min(127, max(1, n["vel"]))),
                            "confidence": 1.0})
    return out


def _tier(energy: float) -> str:
    return "sparse" if energy < 0.35 else ("dense" if energy >= 0.75 else "base")


def _snap8(bars: float) -> int:
    return max(8, int(round(bars / 8.0)) * 8)


LONG_KINDS = {"groove", "peak", "full_groove", "remate"}
EDGE_KINDS = {"intro", "outro", "ritmo_entra"}
KIND_MAP = {"intro": "intro", "outro": "outro", "build": "build", "ritmo_entra": "build", "groove": "groove",
            "full_groove": "groove", "breakdown": "breakdown", "puente": "breakdown", "peak": "peak", "remate": "peak"}
MIN_TOTAL_BARS = 120          # a full song is not shorter than this (about 4 minutes at 128 BPM)


def structure(template: list[dict], rng: random.Random, short: bool, mode: str = "full") -> list[dict]:
    """The style's own arrangement, varied in 8-bar steps: section lengths, and sometimes the peak returns after a short
    breakdown. Elements and energies are copied from the template, never made up. In 'full' mode sections are not
    halved and the song is extended with another groove block until it is a full-length song."""
    secs = [{"name": t["name"], "bars": t["bars"], "elements": list(t["elements"]), "energy": t["energy"]} for t in template]
    for s in secs:
        b = s["bars"]
        if mode == "full":
            if s["name"] == "intro" or s["name"] == "ritmo_entra":
                opts = sorted({max(8, _snap8(b * 0.5)), max(16, _snap8(b * 0.75)) if b >= 24 else _snap8(b)})
            elif s["name"] == "outro":
                opts = sorted({max(16, _snap8(b * 0.75)), max(16, _snap8(b))})
            elif s["name"] in LONG_KINDS:
                opts = sorted({_snap8(b * 0.75), _snap8(b)})
            else:
                opts = [b]
        elif s["name"] in LONG_KINDS or s["name"] in EDGE_KINDS:
            opts = sorted({_snap8(b * 0.5), _snap8(b * 0.75), _snap8(b)})
        elif b >= 16:
            opts = sorted({_snap8(b * 0.5), _snap8(b)})
        else:
            opts = [b]
        s["bars"] = rng.choice(opts)
    peaks = [i for i, s in enumerate(secs) if s["name"] in ("peak", "remate")]
    breaks = [s for s in template if s["name"] in ("breakdown", "puente")]
    if peaks and breaks and rng.random() < 0.5:
        i = peaks[-1]
        bd = dict(name=breaks[0]["name"], bars=8, elements=list(breaks[0]["elements"]), energy=breaks[0]["energy"])
        again = dict(secs[i])
        again["bars"] = _snap8(secs[i]["bars"] * 0.5)
        secs[i + 1:i + 1] = [bd, again]
    if mode == "full" and not short:
        grooves = [i for i, s in enumerate(secs) if KIND_MAP.get(s["name"]) == "groove"]
        guard = 0
        while sum(s["bars"] for s in secs) < MIN_TOTAL_BARS and grooves and guard < 4:
            i = grooves[0]
            extra = dict(secs[i])
            extra["bars"] = 16
            secs.insert(i + 1, extra)
            grooves = [j for j, s in enumerate(secs) if KIND_MAP.get(s["name"]) == "groove"]
            guard += 1
    if short:
        for s in secs:
            s["bars"] = min(s["bars"], 16)
    return secs


def _kick_steps(style_def: dict, lib_patterns: dict) -> set[int]:
    opt = style_def["layers"]["kick"]["base"][0]
    return {int(round(n["start"] * 4)) % 16 for pid in opt for n in lib_patterns[pid]["notes"] if n["vel"] >= 80}


def _kick_overlap(option: list[str], lib_patterns: dict, kick_steps: set[int]) -> float:
    ns = [n for pid in option for n in lib_patterns[pid]["notes"]]
    if not ns:
        return 0.0
    return sum(1 for n in ns if int(round(n["start"] * 4)) % 16 in kick_steps) / len(ns)


def create(style: str, tonic: str | None = None, bpm: float | None = None, seed: int | None = None, short: bool = False,
           swing_pct: float | None = None, mode: str = "full") -> dict:
    """tonic/bpm/swing_pct = None means 'let the seed choose, inside what suits the style'.
    mode 'full': a full-length song where percussion keeps going and layers enter and leave in order;
    mode 'club': the template as written (long DJ intros/outros, drum-only breaks)."""
    if mode not in ("full", "club"):
        raise ValueError("mode must be 'full' or 'club'")
    lib = library()
    if style not in lib["styles"]:
        raise ValueError("unknown style %r; choose one of %s" % (style, ", ".join(STYLES)))
    sd = lib["styles"][style]
    P = lib["patterns"]
    if seed is None:
        seed = random.SystemRandom().randrange(100000, 1000000)
    rng = random.Random(seed)
    # fixed order of draws: key, tempo, swing, structure, then pools
    auto_key = rng.choice(sd["keys_auto"])
    auto_bpm = rng.randint(sd["bpm"]["min"], sd["bpm"]["max"])
    auto_swing = rng.randint(sd["swing_range"][0], sd["swing_range"][1])
    tonic = tonic or auto_key
    if tonic not in TONICS:
        raise ValueError("unknown key %r; choose one of %s" % (tonic, ", ".join(TONICS)))
    bpm = float(bpm or auto_bpm)
    swing = float(auto_swing if swing_pct is None else swing_pct)
    shift = _shift(tonic)
    warnings: list[str] = []
    if not (sd["bpm"]["min"] - 6 <= bpm <= sd["bpm"]["max"] + 6):
        warnings.append("%.0f BPM is outside the usual range for %s (%d-%d)" % (bpm, sd["label"], sd["bpm"]["min"], sd["bpm"]["max"]))

    # for each layer: the pool of alternatives in this song's order (primary first); kick-avoiding styles drop bass
    # grooves that sit mostly on the main kick steps
    kick_steps = _kick_steps(sd, P)
    pools: dict[str, list[list[str]]] = {}
    for lay, spec in sd["layers"].items():
        opts = [list(o) for o in spec["base"]]
        if lay == "bass" and sd.get("bass_avoids_kick"):
            opts = [o for o in opts if _kick_overlap(o, P, kick_steps) <= 0.5] or opts
        rng.shuffle(opts)
        pools[lay] = opts
    occurrence: dict[str, int] = {}

    arrangement = structure(sd["arrangement"], rng, short, mode)
    used_fills: list[str] = []
    secs_in = arrangement
    sections, clips, placements = [], [], []
    notes_by: dict[tuple[str, int], list[dict]] = {}
    used: dict[str, dict] = {}
    log: list[dict] = []
    start_bar = 0
    windows: dict[tuple[str, int], tuple[int, int]] = {}
    kinds = [KIND_MAP.get(x["name"], x["name"]) for x in secs_in]
    for i, s in enumerate(secs_in):
        bars = min(s["bars"], 16) if short else s["bars"]
        kind = kinds[i]
        if mode == "full" and sd.get("profiles") and kind in sd["profiles"]:
            els = list(sd["profiles"][kind])
            if kind == "intro":                                   # the template may add elements (a second intro adds bass)
                els += [e for e in s["elements"] if e not in els and e != "drums"]   # the profile decides the drum layers
        else:
            els = list(s["elements"])
        layers: list[str] = []
        entry_group: dict[str, int] = {}
        for gi, el in enumerate(els):
            mapped = sd["element_map"].get(el)
            if mapped is None or el in ELEMENT_ALIAS:
                a_ = ELEMENT_ALIAS.get(el, el)
                mapped = [a_] if a_ in LAYERS else (mapped or [])
            for lay in mapped:
                if lay not in layers:
                    layers.append(lay)
                    entry_group[lay] = gi
        if mode == "full":
            tier = "dense" if kind == "peak" else ("sparse" if kind in ("intro", "breakdown", "outro") else "base")
        else:
            tier = _tier(s["energy"])
        present: list[str] = []
        for lay in ORDER:
            if lay not in layers:
                continue
            spec = sd["layers"].get(lay)
            if not spec or (mode == "club" and s["energy"] < spec.get("min_energy", 0.0)):
                continue
            if tier == "sparse":
                ids = spec["sparse"] or (pools[lay][0] if mode == "full" else None)
            elif tier == "dense":
                ids = spec["dense"]
            else:
                omit = 0.3 if mode == "club" and lay in ("perc", "lead") else (0.25 if mode == "full" and lay in ("lead", "pad") else 0.0)
                if omit and rng.random() < omit:
                    continue                                   # an optional layer sits this section out
                k = occurrence.get(lay, 0)
                occurrence[lay] = k + 1
                ids = pools[lay][k % len(pools[lay])]          # primary, secondary, primary ...
            if not ids:
                continue
            notes: list[dict] = []
            for pid in ids:
                notes += _tile(P[pid], bars, shift if lay in PITCHED else 0)
            if not notes:
                continue
            notes_by[(lay, i)] = notes
            present.append(lay)
            used[pid] = P[pid]
            log.append({"section": i, "layer": lay, "pattern": "+".join(ids),
                        "name": " + ".join(P[x]["name"] for x in ids), "kind": P[ids[0]]["source"]["kind"]})
        if mode == "full":
            # one new element per 4-bar phrase while a section builds (the owner's one-element rule)
            if kind in ("intro", "build") and bars >= 8:
                eg = {l: (0 if (kind == "build" and l in ("kick", "hat", "clap")) else entry_group[l]) for l in present}
                groups = sorted(set(eg.values()))
                for l in present:
                    windows[(l, i)] = (min(4 * groups.index(eg[l]), bars - 4), bars)
            # strip back two elements in the 4 bars before a peak
            if i + 1 < len(kinds) and kinds[i + 1] == "peak" and kind != "peak" and bars >= 8:
                # only elements that were already playing can be taken away
                playing = [x for x in ("lead", "pad", "chords", "hat", "clap") if x in present
                           and windows.get((x, i), (0, bars))[0] < bars - 4]
                for l in playing[:2]:
                    lo, _ = windows.get((l, i), (0, bars))
                    windows[(l, i)] = (lo, bars - 4)
            # the outro takes elements away in reverse order of entry, so percussion is not dropped at the first bar
            if kind == "outro" and bars >= 8:
                rem = [l for l in sd.get("outro_removal", []) if l in present]
                phases = bars // 4
                for j, l in enumerate(rem):
                    when = 4 * max(1, min(phases - 1, 1 + round(j * (phases - 2) / max(len(rem) - 1, 1))))
                    windows[(l, i)] = (0, when)
        # transition: a short fill on the percussion in the last bar before a clearly bigger section
        nxt = secs_in[i + 1] if i + 1 < len(secs_in) else None
        if nxt and nxt["energy"] >= s["energy"] + 0.2 and sd.get("fill") and bars >= 4:
            fid = rng.choice(sd["fill"])
            fn = _tile(P[fid], 1, 0)
            base = (bars - 1) * BEATS_PER_BAR
            notes_by.setdefault(("perc", i), [])
            notes_by[("perc", i)] += [{**n, "start": n["start"] + base} for n in fn if n["start"] + base < bars * BEATS_PER_BAR]
            log.append({"section": i, "layer": "perc", "pattern": fid, "name": "fill: " + P[fid]["name"],
                        "kind": P[fid]["source"]["kind"]})
        sections.append({"index": i, "start_bar": start_bar, "length_bars": bars, "energy_db": round(-12.0 + 10.0 * s["energy"], 2),
                         "energy_slope_db_per_bar": 0.0, "active_stems": [], "evidence": [], "label": s["name"],
                         "name": "%02d %s | %d" % (i + 1, s["name"].upper(), bars)})
        start_bar += bars

    # apply the entry/exit windows (stagger, strip-back, outro)
    for (lay, i), (lo, hi) in windows.items():
        ns = notes_by.get((lay, i))
        if ns is None:
            continue
        lo_b, hi_b = lo * BEATS_PER_BAR, hi * BEATS_PER_BAR
        notes_by[(lay, i)] = [{**n, "duration": min(n["duration"], hi_b - n["start"])} for n in ns
                              if lo_b <= n["start"] < hi_b and hi_b - n["start"] > 0.04]

    # swing on the 16ths, then the clips
    stems_used: list[str] = []
    for lay in ORDER:
        if any(k[0] == lay for k in notes_by):
            stems_used.append(lay)
    for lay in stems_used:
        name = LAYERS[lay][0]
        for i, s in enumerate(sections):
            n = notes_by.get((lay, i))
            if not n:
                continue
            n = apply_swing(sorted(n, key=lambda x: (x["start"], x["pitch"])), swing)
            end = s["length_bars"] * BEATS_PER_BAR
            n = [{**x, "duration": round(min(x["duration"], end - x["start"]), 4), "source": "created"} for x in n
                 if x["start"] < end - 1e-6 and end - x["start"] >= 0.04]
            cid = "%s|%d" % (name, i)
            clips.append({"id": cid, "stem": name, "name": "%s %s" % (name, s["label"]), "length_beats": end, "notes": n,
                          "loop_period_bars": None, "used_in": [i]})
            placements.append({"stem": name, "section": i, "clip": cid})
            s["active_stems"].append(name)
    stems = [{"name": LAYERS[l][0], "role": LAYERS[l][1], "path": None, "mode": LAYERS[l][2],
              "transcription": {"backend": "stemforge.styles.create/1", "skipped": False, "reason": None, "warnings": [],
                                "source": "created", "stats": {}}} for l in stems_used]
    n_bars = start_bar
    beat = 60.0 / bpm
    bp = {
        "schema_version": 1,
        "song": {"name": "%s in %s (seed %d)" % (sd["label"], tonic, seed), "source_dir": "", "duration_s": round(n_bars * 4 * beat, 2)},
        "global": {"tempo": bpm, "n_bars": n_bars, "time_signature": [4, 4], "steady": True, "drift_beats": 0.0,
                   "downbeat_phase": 0, "downbeat_confidence": 1.0, "downbeat_method": "created",
                   "key": {"tonic": tonic, "mode": "minor", "score": 1.0, "confidence": 1.0},
                   "beats_s": [round(k * beat, 4) for k in range(n_bars * 4 + 8)],
                   "quantize": {"resolution_beats": 0.25, "strength": 1.0}},
        "sections": sections, "stems": stems, "warnings": warnings, "clips": clips, "placements": placements,
        "clip_min_confidence": 0.0,
    }
    bp["generation"] = {"method": "styles.create/1", "style": style, "tonic": tonic, "bpm": bpm, "swing_pct": swing, "seed": seed,
                        "short": short, "mode": mode,
                        "windows": [{"layer": l, "section": i, "from_bar": lo + 1, "to_bar": hi} for (l, i), (lo, hi) in sorted(windows.items())], "layers": log, "refs": sd["refs"], "checks": checks(bp)}
    return bp


def checks(bp: dict) -> dict:
    """Plain facts about what was assembled, e.g. how often the bass lands on a kick step."""
    out: dict = {}
    clips = {c["id"]: c for c in bp["clips"]}

    def steps_of(stem, min_vel=0):
        res = []
        for p in bp["placements"]:
            if p["stem"] == stem:
                for n in clips[p["clip"]]["notes"]:
                    if n["velocity"] >= min_vel:
                        st = n["start"] % 4.0 * 4
                        res.append(int(round(st)) % 16)
        return res
    bass = steps_of("Bass")
    kick_steps = set(steps_of("Kick", min_vel=80))   # the style's real kick positions; ghost kicks do not count
    if bass:
        out["bass_notes"] = len(bass)
        if kick_steps:
            out["bass_on_kick_steps_pct"] = round(100.0 * sum(1 for s in bass if s in kick_steps) / len(bass), 1)
        out["bass_on_offbeat_8ths_pct"] = round(100.0 * sum(1 for s in bass if s % 4 == 2) / len(bass), 1)
    out["layers"] = sorted({c["stem"] for c in bp["clips"]})
    out["bars"] = bp["global"]["n_bars"]
    # rhythm continuity: how many sections have some percussion (hats or perc), and does the last section still have it
    secs = bp["sections"]
    has = [any(n in s["active_stems"] for n in ("Hats", "Perc")) for s in secs]
    out["sections_with_percussion"] = "%d of %d" % (sum(has), len(secs))
    out["percussion_in_last_section"] = bool(has and has[-1])
    out["empty_core_slots"] = sum(1 for s in secs if s["label"] not in ("breakdown", "puente", "intro") for n in ("Kick", "Bass")
                                  if n not in s["active_stems"] and n in out["layers"])
    return out


def describe(bp: dict) -> list[str]:
    """One plain line per layer: which patterns it uses and where they come from."""
    g = bp["generation"]
    by: dict[str, dict] = {}
    for e in g["layers"]:
        d = by.setdefault(e["layer"], {})
        d.setdefault(e["name"], e["kind"])
    kind = {"notebooklm": "your NotebookLM research", "documented": "published recipe", "measured": "measured from real loops"}
    out = []
    for lay in ORDER:
        if lay in by:
            names = "; ".join("%s (%s)" % (n, kind.get(k, k)) for n, k in list(by[lay].items())[:4])
            out.append("%s: %s" % (LAYERS[lay][0], names))
    return out
