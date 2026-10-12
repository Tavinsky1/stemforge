"""Create a song skeleton from zero in one of four styles. Deterministic: no randomness, no generated notes.

Everything written comes from the style library (library/styles.json): patterns from the owner's NotebookLM research,
bar patterns measured from real loops, and documented recipes, each with its source. The arrangement is the style's own
(knowledge/arrangement/*.json). This module only ASSEMBLES: it picks, for every section, the pattern its energy and
elements call for, tiles it over the bars, transposes pitched parts to the key, and applies the style's swing.

`take` rotates through the alternatives the library holds for a layer (take 0 is the first/most typical). It never
invents anything.
"""
from __future__ import annotations

import json
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


def create(style: str, tonic: str | None = None, bpm: float | None = None, take: int = 0, short: bool = False,
           swing_pct: float | None = None) -> dict:
    lib = library()
    if style not in lib["styles"]:
        raise ValueError("unknown style %r; choose one of %s" % (style, ", ".join(STYLES)))
    sd = lib["styles"][style]
    P = lib["patterns"]
    tonic = tonic or sd["tonic"]
    if tonic not in TONICS:
        raise ValueError("unknown key %r; choose one of %s" % (tonic, ", ".join(TONICS)))
    bpm = float(bpm or sd["bpm"]["default"])
    swing = float(sd["swing_pct"] if swing_pct is None else swing_pct)
    shift = _shift(tonic)
    warnings: list[str] = []
    if not (sd["bpm"]["min"] - 6 <= bpm <= sd["bpm"]["max"] + 6):
        warnings.append("%.0f BPM is outside the usual range for %s (%d-%d)" % (bpm, sd["label"], sd["bpm"]["min"], sd["bpm"]["max"]))

    secs_in = sd["arrangement"]
    sections, clips, placements = [], [], []
    notes_by: dict[tuple[str, int], list[dict]] = {}
    used: dict[str, dict] = {}
    log: list[dict] = []
    start_bar = 0
    for i, s in enumerate(secs_in):
        bars = min(s["bars"], 16) if short else s["bars"]
        layers: list[str] = []
        for el in s["elements"]:
            for lay in sd["element_map"].get(el, []):
                if lay not in layers:
                    layers.append(lay)
        tier = _tier(s["energy"])
        for lay in ORDER:
            if lay not in layers:
                continue
            spec = sd["layers"].get(lay)
            if not spec or s["energy"] < spec.get("min_energy", 0.0):
                continue
            ids = spec["sparse"] if tier == "sparse" else (spec["dense"] if tier == "dense" else
                                                             spec["base"][take % len(spec["base"])])
            if not ids:
                continue
            notes: list[dict] = []
            for pid in ids:
                notes += _tile(P[pid], bars, shift if lay in PITCHED else 0)
            if not notes:
                continue
            notes_by[(lay, i)] = notes
            used[pid] = P[pid]
            log.append({"section": i, "layer": lay, "pattern": "+".join(ids),
                        "name": " + ".join(P[x]["name"] for x in ids), "kind": P[ids[0]]["source"]["kind"]})
        # transition: a short fill on the percussion in the last bar before a clearly bigger section
        nxt = secs_in[i + 1] if i + 1 < len(secs_in) else None
        if nxt and nxt["energy"] >= s["energy"] + 0.2 and sd.get("fill") and bars >= 4:
            fid = sd["fill"][take % len(sd["fill"])]
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
        "song": {"name": "%s in %s (created)" % (sd["label"], tonic), "source_dir": "", "duration_s": round(n_bars * 4 * beat, 2)},
        "global": {"tempo": bpm, "n_bars": n_bars, "time_signature": [4, 4], "steady": True, "drift_beats": 0.0,
                   "downbeat_phase": 0, "downbeat_confidence": 1.0, "downbeat_method": "created",
                   "key": {"tonic": tonic, "mode": "minor", "score": 1.0, "confidence": 1.0},
                   "beats_s": [round(k * beat, 4) for k in range(n_bars * 4 + 8)],
                   "quantize": {"resolution_beats": 0.25, "strength": 1.0}},
        "sections": sections, "stems": stems, "warnings": warnings, "clips": clips, "placements": placements,
        "clip_min_confidence": 0.0,
    }
    bp["generation"] = {"method": "styles.create/1", "style": style, "tonic": tonic, "bpm": bpm, "swing_pct": swing, "take": take,
                        "short": short, "layers": log, "refs": sd["refs"], "checks": checks(bp)}
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
