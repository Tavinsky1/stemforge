from __future__ import annotations

import numpy as np

SR = 22050


def load_mono(path: str, sr: int = SR) -> np.ndarray:
    import librosa
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y.astype(np.float32)


def match_lengths(signals: list[np.ndarray]) -> list[np.ndarray]:
    n = max(len(s) for s in signals)
    return [np.pad(s, (0, n - len(s))) for s in signals]
