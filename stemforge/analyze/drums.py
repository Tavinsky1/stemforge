"""Drum transcription: onset detection + a simple spectral classifier -> GM drum notes."""
from __future__ import annotations

import numpy as np

from . import onsets

GM = {"kick": 36, "snare": 38, "hat_closed": 42, "hat_open": 46, "perc": 75}


def _band(spec_mag: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    m = (freqs >= lo) & (freqs < hi)
    return float(spec_mag[m].sum())


def classify_hit(seg: np.ndarray, sr: int, tail: np.ndarray) -> tuple[str, float]:
    """seg: ~60 ms from the onset; tail: 60..200 ms after. Returns (class, confidence 0..1)."""
    w = seg * np.hanning(len(seg))
    mag = np.abs(np.fft.rfft(w, 2048))
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    total = mag.sum() + 1e-9
    low = _band(mag, freqs, 20, 150) / total
    mid = _band(mag, freqs, 150, 2500) / total
    high = _band(mag, freqs, 5000, sr / 2) / total
    centroid = float((mag * freqs).sum() / total)
    tail_e = float(np.sqrt(np.mean(tail ** 2))) if len(tail) else 0.0
    seg_e = float(np.sqrt(np.mean(seg ** 2))) + 1e-9
    decay = tail_e / seg_e   # long ring -> open hat
    if low > 0.45 and centroid < 600:
        return "kick", float(min(1.0, 0.5 + low))
    if high > 0.30 and centroid > 4000:
        return ("hat_open" if decay > 0.35 else "hat_closed"), float(min(1.0, 0.5 + high))
    if mid > 0.45 and centroid > 800:
        return "snare", float(min(1.0, 0.4 + mid / 2))
    return "perc", 0.35


def transcribe_drums(y: np.ndarray, sr: int, fixed_class: str | None = None):
    """Returns notes in seconds: {start_s,end_s,pitch,confidence,velocity_raw,cls}."""
    import librosa
    times = onsets.pick(onsets.flux(y, sr), sr)
    notes = []
    peak = np.max(np.abs(y)) + 1e-9
    for t in times:
        a = int(t * sr)
        seg = y[a:a + int(0.06 * sr)]
        tail = y[a + int(0.06 * sr):a + int(0.20 * sr)]
        if len(seg) < 256:
            continue
        if fixed_class:
            cls, conf = fixed_class, 0.9
            if cls == "hat":
                cls = "hat_open" if (np.sqrt(np.mean(tail ** 2)) / (np.sqrt(np.mean(seg ** 2)) + 1e-9)) > 0.35 else "hat_closed"
        else:
            cls, conf = classify_hit(seg, sr, tail)
        notes.append({"start_s": float(t), "end_s": float(t) + 0.1, "pitch": GM.get(cls, GM["perc"]),
                      "confidence": conf, "level": float(np.max(np.abs(seg)) / peak), "cls": cls})
    # a weak hit right after a much louder one is the ring-out of that hit, not a new hit
    out = []
    for n in notes:
        if out and n["start_s"] - out[-1]["start_s"] < 0.2 and n["level"] < 0.25 * out[-1]["level"]:
            continue
        out.append(n)
    if out:
        ref = np.percentile([n["level"] for n in out], 90)
        for n in out:
            if n["level"] < 0.2 * ref:
                n["confidence"] *= 0.5   # ghost-level hit: kept, flagged low confidence
    return out
