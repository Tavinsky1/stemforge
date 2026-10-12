"""Mine bass grooves from real loops: where the hits sit in the bar, which note, how hard, how long.

A dev tool: it reads audio loops with a known tempo, snaps every hit to the bar's 16-step grid (with the loop's own swing),
decodes the pitch relative to the loop's tonic, and counts which bar patterns recur. The result (a JSON library with the
source files and counts) is what the app uses; the app never reads the original loops.
"""
from __future__ import annotations

import collections
import os
import re

import numpy as np

from .. import resynth

BEATS = 4


def loop_bars(duration: float, bpm: float) -> int | None:
    """Number of whole bars if the loop length matches the stated tempo (within 6%), else None."""
    bar = 4 * 60.0 / bpm
    n = max(1, int(round(duration / bar)))
    return n if abs(duration - n * bar) / (n * bar) < 0.06 and n <= 16 else None


def bpm_from_name(name: str) -> float | None:
    n = os.path.basename(name).lower()
    for pat in (r"(\d{2,3})\s*bpm", r"bpm\s*[_-]?\s*(\d{2,3})", r"_(\d{2,3})_", r"[ _-](\d{2,3})[ _-]"):
        m = re.search(pat, n)
        if m and 60 <= int(m.group(1)) <= 200:
            return float(m.group(1))
    return None


def phase_offset(t_on: np.ndarray, beat: float) -> float:
    """Constant offset (in beats, within +-1/8) between the loop's hits and the 16th grid."""
    if len(t_on) == 0:
        return 0.0
    ph = (t_on / beat) % 0.25
    ph = np.where(ph > 0.125, ph - 0.25, ph)
    return float(np.median(ph))


def swing_of(t_on: np.ndarray, beat: float, off: float) -> float:
    ph = ((t_on / beat) - off) % 1.0
    e = ph[(ph >= 0.18) & (ph <= 0.42)]
    return float(np.median(e)) if len(e) >= 4 else 0.25


def mine_loop(path: str, bpm: float, lo: int = 24, hi: int = 72, bars_override: int | None = None) -> dict | None:
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    dur = len(y) / sr
    bars = bars_override or loop_bars(dur, bpm)
    if not bars:
        return None
    beat = 60.0 / bpm
    C, _ = resynth._cqt(y, sr, m0=24, n_bins=96, hop=256)
    t_on, strength, _ = resynth._onset_times(C, sr, 256, y)
    keep = strength >= 0.18
    t_on = t_on[keep]
    if len(t_on) < 4:
        return None
    off = phase_offset(t_on, beat)
    e_pos = swing_of(t_on, beat, off)
    groove = {"grid_offset_beats": off, "e_position_beats": e_pos if 0.25 <= e_pos <= 0.36 else 0.25,
              "a_position_beats": 0.75 + (e_pos - 0.25) if 0.25 <= e_pos <= 0.36 else 0.75}
    beats = np.arange(0, bars * 4 + 4) * beat
    ev = resynth.extract_events(path, beats, groove, lo, hi)
    ev = [e for e in ev if e["beat"] // BEATS < bars]
    if len(ev) < 4:
        return None
    resynth.snap_outliers(ev)
    pcs = collections.Counter(e["pitches"][0][0] % 12 for e in ev)
    tonic = pcs.most_common(1)[0][0]
    roots = [e["pitches"][0][0] for e in ev if e["pitches"][0][0] % 12 == tonic]
    base = int(np.median(roots))
    lv = np.array([e.get("level_db", 0.0) for e in ev])
    order = lv.argsort().argsort() / max(len(lv) - 1, 1)
    notes = []
    for e, r in zip(ev, order):
        notes.append({"bar": e["beat"] // BEATS, "step": (e["beat"] % BEATS) * 4 + e["step"], "semi": int(e["pitches"][0][0] - base),
                      "vel": float(r), "dur": float(e.get("dur", 0.25))})
    return {"file": os.path.basename(path), "bpm": bpm, "bars": bars, "tonic_midi": base, "swing_e": round(e_pos, 3),
            "notes": notes}


def bar_patterns(loop: dict) -> list[tuple]:
    out = []
    for b in range(loop["bars"]):
        ns = sorted((n["step"], n["semi"]) for n in loop["notes"] if n["bar"] == b)
        if ns:
            out.append(tuple(ns))
    return out


def summarize(loops: list[dict], top: int = 8) -> dict:
    """Aggregate the recurring bar patterns of a style."""
    pat_count: collections.Counter = collections.Counter()
    pat_src: dict[tuple, set] = collections.defaultdict(set)
    pat_notes: dict[tuple, list] = collections.defaultdict(list)
    step_hist = np.zeros(16)
    n_bars = 0
    dens = []
    semis = collections.Counter()
    for lp in loops:
        for p in bar_patterns(lp):
            n_bars += 1
            pat_count[p] += 1
            pat_src[p].add(lp["file"])
            dens.append(len(p))
            for s, sm in p:
                step_hist[s] += 1
                semis[sm] += 1
        for n in lp["notes"]:
            pass
    for lp in loops:
        for n in lp["notes"]:
            key = None
        # velocity and length per (step) across the style
    vel_by_step = collections.defaultdict(list)
    dur_by_step = collections.defaultdict(list)
    for lp in loops:
        for n in lp["notes"]:
            vel_by_step[n["step"]].append(n["vel"])
            dur_by_step[n["step"]].append(n["dur"])
    ranked = []
    for p, c in pat_count.most_common():
        if len(p) < 2:
            continue
        ranked.append({"pattern": [{"step": s, "semi": sm} for s, sm in p], "count": c, "sources": sorted(pat_src[p])[:6],
                       "n_sources": len(pat_src[p])})
        if len(ranked) >= top * 3:
            break
    return {
        "loops": [{"file": l["file"], "bpm": l["bpm"], "bars": l["bars"]} for l in loops],
        "n_bars": n_bars,
        "notes_per_bar_median": float(np.median(dens)) if dens else 0.0,
        "step_probability": [round(float(x / max(step_hist.sum(), 1)), 3) for x in step_hist],
        "kick_step_share": round(float(sum(step_hist[i] for i in (0, 4, 8, 12)) / max(step_hist.sum(), 1)), 3),
        "interval_share": {str(k): round(v / max(sum(semis.values()), 1), 3) for k, v in semis.most_common(10)},
        "velocity_by_step": {str(s): round(float(np.mean(v)), 2) for s, v in sorted(vel_by_step.items())},
        "duration_by_step": {str(s): round(float(np.median(v)), 2) for s, v in sorted(dur_by_step.items())},
        "patterns": ranked,
    }


def ascii_pattern(p: list[dict]) -> str:
    row = ["."] * 16
    for n in p:
        row[n["step"]] = {0: "R"}.get(n["semi"], "o" if n["semi"] < 0 else ("^" if n["semi"] >= 12 else "x"))
    return " ".join("".join(row[i:i + 4]) for i in range(0, 16, 4))


def jaccard(a: set, b: set) -> float:
    u = len(a | b)
    return 1.0 if u == 0 else len(a & b) / u


def loop_cells(loop: dict, similarity: float = 0.6, min_share: float = 0.2) -> list[dict]:
    """The loop's repeating bar patterns: alike bars are merged, a step stays when most bars of its cluster have it.
    Returns cells {pattern: [(step, semi, vel, dur)], share, bars}."""
    bars = {}
    for n in loop["notes"]:
        bars.setdefault(n["bar"], []).append(n)
    clusters: list[list[int]] = []
    for b in sorted(bars):
        s = {n["step"] for n in bars[b]}
        for c in clusters:
            if jaccard(s, {n["step"] for n in bars[c[0]]}) >= similarity:
                c.append(b)
                break
        else:
            clusters.append([b])
    cells = []
    total = max(len(bars), 1)
    for c in clusters:
        if len(c) / total < min_share and len(clusters) > 1:
            continue
        pat = []
        for step in range(16):
            hits = [n for b in c for n in bars[b] if n["step"] == step]
            if len(hits) / len(c) >= 0.5:
                semis = [h["semi"] for h in hits]
                pat.append({"step": step, "semi": max(set(semis), key=semis.count),
                            "vel": round(float(np.median([h["vel"] for h in hits])), 2),
                            "dur": round(float(np.median([h["dur"] for h in hits])), 2)})
        if len(pat) >= 2:
            cells.append({"pattern": pat, "share": round(len(c) / total, 2), "bars": len(c), "file": loop["file"], "bpm": loop["bpm"]})
    return cells


def typical_cells(loops: list[dict], top: int = 10) -> list[dict]:
    """Rank all cells of a style by how typical they are: mean step-overlap with the other sources' cells."""
    cells = [c for lp in loops for c in loop_cells(lp)]
    sets = [{p["step"] for p in c["pattern"]} for c in cells]
    out = []
    for i, c in enumerate(cells):
        others = [jaccard(sets[i], sets[j]) for j, d in enumerate(cells) if d["file"] != c["file"]]
        c = dict(c)
        c["typicality"] = round(float(np.mean(others)) if others else 0.0, 3)
        out.append(c)
    out.sort(key=lambda c: (-c["typicality"], -c["share"]))
    # drop near-duplicates
    kept: list[dict] = []
    for c in out:
        s = {p["step"] for p in c["pattern"]}
        if all(jaccard(s, {p["step"] for p in k["pattern"]}) < 0.85 for k in kept):
            kept.append(c)
        if len(kept) >= top:
            break
    return kept
