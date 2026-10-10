"""Seconds -> beats, quantize to the grid, clean overlaps and micro-notes."""
from __future__ import annotations

from .grid import BeatGrid


def to_beats(notes_s: list[dict], grid: BeatGrid) -> list[dict]:
    out = []
    for n in notes_s:
        s = float(grid.to_beat(n["start_s"]))
        e = float(grid.to_beat(n["end_s"]))
        d = dict(n)
        d["start"], d["duration"] = s, max(e - s, 0.0)
        out.append(d)
    return out


def velocity_from_level(levels: list[float], lo: int = 45, hi: int = 120) -> list[int]:
    if not levels:
        return []
    import numpy as np
    a = np.asarray(levels, dtype=float)
    p5, p95 = np.percentile(a, 5), np.percentile(a, 95)
    x = np.clip((a - p5) / (p95 - p5 + 1e-9), 0, 1)
    return [int(round(lo + v * (hi - lo))) for v in x]


def quantize(notes: list[dict], resolution: float = 0.25, strength: float = 1.0, min_dur: float = 0.1,
             drums: bool = False, mono: bool = False) -> tuple[list[dict], dict]:
    """
    resolution: grid in beats (0.25 = 16th). strength: 1.0 snap fully, 0.0 keep raw timing (humanize).
    Returns (cleaned notes, stats).
    """
    stats = {"input": len(notes), "dropped_negative": 0, "dropped_micro": 0, "merged": 0, "dropped_dupe": 0}
    out = []
    for n in notes:
        if n["start"] < -0.05:
            stats["dropped_negative"] += 1   # before the first downbeat (pickup); reported, not shifted
            continue
        if not drums and n["duration"] < min_dur:
            stats["dropped_micro"] += 1
            continue
        q = round(n["start"] / resolution) * resolution
        start = max(0.0, n["start"] + strength * (q - n["start"]))
        if drums:
            dur = 0.1
        else:
            qd = max(resolution, round(n["duration"] / resolution) * resolution)
            dur = n["duration"] + strength * (qd - n["duration"])
        m = dict(n)
        m["start"], m["duration"] = round(start, 4), round(max(dur, 0.05), 4)
        out.append(m)

    out.sort(key=lambda n: (n["pitch"], n["start"]))
    merged = []
    for n in out:   # same pitch: drop duplicates at the same slot, merge touching/overlapping notes
        if merged and merged[-1]["pitch"] == n["pitch"]:
            p = merged[-1]
            if abs(p["start"] - n["start"]) < 1e-6:
                stats["dropped_dupe"] += 1
                if n["confidence"] > p["confidence"]:
                    merged[-1] = n
                continue
            if not drums and n["start"] <= p["start"] + p["duration"] + 0.02:
                p["duration"] = round(n["start"] + n["duration"] - p["start"], 4)
                p["confidence"] = min(p["confidence"], n["confidence"])
                stats["merged"] += 1
                continue
            if not drums and p["start"] + p["duration"] > n["start"]:
                p["duration"] = round(n["start"] - p["start"], 4)
        merged.append(n)
    merged.sort(key=lambda n: (n["start"], n["pitch"]))
    if mono and not drums:   # single voice: each note ends where the next begins
        for a, b in zip(merged, merged[1:]):
            if a["start"] + a["duration"] > b["start"]:
                a["duration"] = round(max(b["start"] - a["start"], 0.05), 4)
    stats["output"] = len(merged)
    return merged, stats
