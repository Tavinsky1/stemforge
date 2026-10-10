"""Section boundaries from all stems together, with the evidence for each boundary."""
from __future__ import annotations

import numpy as np

from .grid import BEATS_PER_BAR, BeatGrid

ACTIVE_FRAC = 0.15   # a stem is "active" in a bar if its level is above this fraction of its own p95


def bar_levels(y: np.ndarray, sr: int, grid: BeatGrid, n_bars: int) -> np.ndarray:
    """RMS per bar for one stem."""
    out = np.zeros(n_bars)
    bar_beats = np.arange(n_bars + 1) * BEATS_PER_BAR
    edges = (grid.to_time(bar_beats) * sr).astype(int)
    for b in range(n_bars):
        seg = y[max(edges[b], 0):max(edges[b + 1], 0)]
        out[b] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    return out


def activity(levels: np.ndarray) -> np.ndarray:
    ref = np.percentile(levels, 95) + 1e-9
    return levels / ref


def find_sections(stem_levels: dict[str, np.ndarray], min_bars: int = 4, window: int = 4, thresh: float = 0.35):
    """
    stem_levels: name -> per-bar RMS. Returns list of section dicts with evidence.
    Novelty at bar b = distance between mean activity of the `window` bars before and after.
    """
    names = list(stem_levels)
    n_bars = len(next(iter(stem_levels.values())))
    A = np.stack([np.clip(activity(stem_levels[n]), 0, 1.5) for n in names], axis=1)  # bars x stems
    total = np.sqrt((np.stack([stem_levels[n] for n in names]) ** 2).sum(axis=0))
    total_db = 20 * np.log10(total / (total.max() + 1e-9) + 1e-6)

    nov = np.zeros(n_bars)
    for b in range(1, n_bars):
        lo, hi = max(0, b - window), min(n_bars, b + window)
        before, after = A[lo:b], A[b:hi]
        if len(before) and len(after):
            nov[b] = np.linalg.norm(before.mean(axis=0) - after.mean(axis=0)) / np.sqrt(len(names))

    cands = [b for b in range(1, n_bars) if nov[b] >= thresh and nov[b] >= nov[max(0, b - 2):b + 3].max() - 1e-9]
    # prefer 4-bar-aligned boundaries (snap when within 1 bar)
    snapped = []
    for b in cands:
        s = int(round(b / 4.0) * 4)
        snapped.append(s if abs(s - b) <= 1 and s > 0 else b)
    bounds = [0]
    for b in sorted(set(snapped)):
        if b - bounds[-1] >= min_bars and n_bars - b >= min_bars:
            bounds.append(b)
    bounds.append(n_bars)

    sections = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        evidence = []
        if s > 0:
            before = A[max(0, s - window):s].mean(axis=0)
            after = A[s:min(n_bars, s + window)].mean(axis=0)
            for j, n in enumerate(names):
                d = after[j] - before[j]
                if abs(d) >= 0.4:
                    evidence.append({"stem": n, "event": "enters" if d > 0 else "leaves",
                                     "before": round(float(before[j]), 2), "after": round(float(after[j]), 2)})
            evidence.append({"metric": "energy_change_db",
                             "value": round(float(total_db[s:min(n_bars, s + window)].mean() - total_db[max(0, s - window):s].mean()), 2),
                             "novelty": round(float(nov[s]), 3)})
        sections.append({
            "index": i, "start_bar": s, "length_bars": e - s,
            "energy_db": round(float(total_db[s:e].mean()), 2),
            "energy_slope_db_per_bar": round(float(np.polyfit(np.arange(e - s), total_db[s:e], 1)[0]) if e - s > 1 else 0.0, 3),
            "active_stems": [n for j, n in enumerate(names) if A[s:e, j].mean() >= 0.3],
            "evidence": evidence,
        })
    return sections


def label_sections(sections: list[dict], drum_names: list[str], bass_names: list[str]) -> None:
    """Label from measurements only (drums present, bass present, energy rank, slope)."""
    n = len(sections)
    emax = max(s["energy_db"] for s in sections)
    emin = min(s["energy_db"] for s in sections)
    span = max(emax - emin, 1e-6)
    for i, s in enumerate(sections):
        rel = (s["energy_db"] - emin) / span
        has_drums = any(d in s["active_stems"] for d in drum_names) if drum_names else True
        has_bass = any(b in s["active_stems"] for b in bass_names) if bass_names else True
        prev = sections[i - 1]["label"] if i else None
        if i == 0 and (not has_drums or rel < 0.5):
            label = "intro"
        elif i == n - 1 and rel < 0.6:
            label = "outro"
        elif not has_drums and i not in (0, n - 1):
            label = "breakdown"
        elif s["energy_slope_db_per_bar"] > 0.35 and rel < 0.9:
            label = "build"
        elif rel >= 0.85:
            label = "drop" if prev in ("breakdown", "build") else "peak"
        else:
            label = "groove"
        s["label"] = label
        s["name"] = "%02d %s | %d" % (i + 1, label.upper(), s["length_bars"])
