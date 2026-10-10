"""One onset-flux implementation shared by the grid and the drum transcriber, so they agree on timing."""
from __future__ import annotations

import numpy as np

N_FFT = 1024
HOP = 256


def flux(y: np.ndarray, sr: int, fmin: float = 0.0, fmax: float | None = None) -> np.ndarray:
    import librosa
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    f = np.fft.rfftfreq(N_FFT, 1.0 / sr)
    sel = (f >= fmin) & (f <= (fmax if fmax else sr / 2))
    L = np.log1p(100.0 * S[sel])
    out = np.maximum(0.0, np.diff(L, axis=1)).sum(axis=0)
    return np.concatenate([[0.0], out])


def pick(env: np.ndarray, sr: int, delta: float = 0.15) -> np.ndarray:
    import librosa
    env = env / (env.max() + 1e-9)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=HOP, backtrack=False, delta=delta)
    return frames * HOP / sr
