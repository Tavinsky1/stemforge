"""Tempo, beat/downbeat grid and drift handling. All note times are converted to beats via this grid."""
from __future__ import annotations

import numpy as np

from . import onsets

BEATS_PER_BAR = 4  # 4/4 assumed; recorded in the blueprint so the builder never guesses


class BeatGrid:
    """Maps seconds <-> beats using tracked beat times (handles tempo drift)."""

    def __init__(self, beat_times: np.ndarray):
        self.beat_times = np.asarray(beat_times, dtype=float)  # beat_times[i] = time of beat i (i=0 is a downbeat)

    def to_beat(self, t):
        t = np.asarray(t, dtype=float)
        bt = self.beat_times
        idx = np.arange(len(bt), dtype=float)
        out = np.interp(t, bt, idx)
        lo = t < bt[0]
        hi = t > bt[-1]
        if np.any(lo):
            out = np.where(lo, (t - bt[0]) / (bt[1] - bt[0]), out)
        if np.any(hi):
            out = np.where(hi, (len(bt) - 1) + (t - bt[-1]) / (bt[-1] - bt[-2]), out)
        return out

    def to_time(self, beat):
        beat = np.asarray(beat, dtype=float)
        bt = self.beat_times
        idx = np.arange(len(bt), dtype=float)
        out = np.interp(beat, idx, bt)
        hi = beat > idx[-1]
        if np.any(hi):
            out = np.where(hi, bt[-1] + (beat - idx[-1]) * (bt[-1] - bt[-2]), out)
        return out

    @property
    def n_bars(self) -> int:
        return (len(self.beat_times) - 1) // BEATS_PER_BAR


HOP = onsets.HOP


def _comb_score(env: np.ndarray, fps: float, period: float, phase: float) -> float:
    t = np.arange(phase, len(env) / fps, period)
    return float(np.interp(t * fps, np.arange(len(env)), env).mean())


def detect_grid(y_rhythm: np.ndarray, sr: int, duration: float, drift_tol_beats: float = 0.06):
    """
    Beat grid from a rhythm-heavy signal (drums+bass if available).
    1. global tempo + phase by comb-filtering the onset envelope (low band weighted: kicks/bass),
    2. local phase per chunk of the song; a straight line fits -> constant grid, else piecewise (drift kept),
    3. downbeat = beat phase (0..3) with most low-band energy.
    Returns (BeatGrid, info).
    """
    import librosa

    full = onsets.flux(y_rhythm, sr)
    low = onsets.flux(y_rhythm, sr, fmax=200.0)
    env = 0.7 * low / (low.max() + 1e-9) + 0.3 * full / (full.max() + 1e-9)
    fps = sr / HOP
    tempo0 = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=sr, hop_length=HOP, start_bpm=120.0))[0])
    while tempo0 < 70:
        tempo0 *= 2
    while tempo0 > 180:
        tempo0 /= 2

    best = (-1.0, tempo0, 0.0)
    for bpm in np.arange(tempo0 * 0.96, tempo0 * 1.04, 0.1):
        period = 60.0 / bpm
        for ph in np.linspace(0, period, 40, endpoint=False):
            s = _comb_score(env, fps, period, ph)
            if s > best[0]:
                best = (s, bpm, ph)
    _, bpm, ph = best
    period = 60.0 / bpm
    # refine phase finely at the chosen tempo
    fine = [(_comb_score(env, fps, period, ph + d), ph + d) for d in np.linspace(-period / 40, period / 40, 21)]
    ph = max(fine)[1]

    n_beats = int((duration - ph) / period) + 1
    n_chunks = int(np.clip(n_beats // 16, 2, 8))
    k_edges = np.linspace(0, n_beats, n_chunks + 1).astype(int)
    centers, deltas = [], []
    for a, b in zip(k_edges[:-1], k_edges[1:]):
        if b - a < 4:
            continue
        ks = np.arange(a, b)
        cand = np.linspace(-0.3 * period, 0.3 * period, 61)
        sc = [float(np.interp((ph + ks * period + d) * fps, np.arange(len(env)), env).mean()) for d in cand]
        centers.append((a + b) / 2.0)
        deltas.append(float(cand[int(np.argmax(sc))]))
    centers, deltas = np.array(centers), np.array(deltas)
    ks_all = np.arange(-16, n_beats + 16)
    if len(centers) >= 2:
        slope, icpt = np.polyfit(centers, deltas, 1)
        resid = deltas - (slope * centers + icpt)
        drift_beats = float(np.max(np.abs(resid)) / period)
    else:
        slope, icpt, drift_beats = 0.0, 0.0, 0.0
    steady = drift_beats <= drift_tol_beats
    if steady:
        period2 = period + slope * period   # slope is seconds-of-delta per beat
        t_all = ph + icpt + ks_all * period2
        bpm_out = 60.0 / period2
    else:
        off = np.interp(ks_all, centers, deltas)
        t_all = ph + ks_all * period + off
        bpm_out = 60.0 / float(np.median(np.diff(t_all)))

    valid = np.where(t_all >= -0.05)[0]
    low_n = low / (low.max() + 1e-9)
    beat_str = np.interp(t_all * fps, np.arange(len(low_n)), low_n)
    phase_score = [float(np.sum(beat_str[valid][p::BEATS_PER_BAR])) for p in range(BEATS_PER_BAR)]
    phase = int(np.argmax(phase_score))
    srt = sorted(phase_score)
    conf = (srt[-1] - srt[-2]) / (srt[-1] + 1e-9)
    method = "low-band energy"
    if conf < 0.15:
        # four-on-the-floor: every beat looks alike. Assume the first strong low-band event is bar 1 beat 1.
        loud = np.where(low_n > 0.3)[0]
        if len(loud):
            t_first = loud[0] / fps
            near = valid[int(np.argmin(np.abs(t_all[valid] - t_first)))]
            phase = int(np.where(valid == near)[0][0] % BEATS_PER_BAR)
            method = "first strong event assumed to be a downbeat"
    start = valid[phase]
    end = int(np.searchsorted(t_all, duration)) + 4
    grid = BeatGrid(t_all[start:end])
    info = {
        "tempo": round(float(bpm_out), 3),
        "drift_beats": round(drift_beats, 3),
        "steady": bool(steady),
        "downbeat_phase": phase,
        "downbeat_confidence": round(float(conf), 3),
        "downbeat_method": method,
        "first_downbeat_s": round(float(grid.beat_times[0]), 4),
        "time_signature": [BEATS_PER_BAR, 4],
    }
    return grid, info
