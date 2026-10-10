"""Key/mode detection (Krumhansl-Schmuckler) on the pitched stems only."""
from __future__ import annotations

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_key(chroma_mean: np.ndarray) -> dict:
    scores = []
    for tonic in range(12):
        for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
            r = np.corrcoef(chroma_mean, np.roll(prof, tonic))[0, 1]
            scores.append((float(r), NOTE_NAMES[tonic], mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    # confidence = how far ahead of the runner-up (relative-major/minor confusion shows up as a small margin)
    margin = best[0] - second[0]
    return {
        "tonic": best[1], "mode": best[2],
        "score": round(best[0], 3), "confidence": round(float(np.clip(margin / 0.1, 0, 1)), 3),
        "alt": {"tonic": second[1], "mode": second[2], "score": round(second[0], 3)},
    }


def chroma_of(y: np.ndarray, sr: int) -> np.ndarray:
    import librosa
    c = librosa.feature.chroma_cqt(y=librosa.effects.harmonic(y), sr=sr)
    return c.mean(axis=1)
