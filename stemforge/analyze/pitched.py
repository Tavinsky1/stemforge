"""Pitched transcription (bass/melody/chords). Never invents notes: if no backend can do the job, returns nothing + a reason."""
from __future__ import annotations

import numpy as np

# Frequency windows per role keep the model out of the wrong octave.
FREQ_RANGE = {"bass": (30.0, 400.0), "vocals": (80.0, 1200.0)}


def backend_name() -> str:
    try:
        import basic_pitch  # noqa: F401
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            p = str(ICASSP_2022_MODEL_PATH)
            kind = "coreml" if "mlpackage" in p else "onnx" if p.endswith(".onnx") else "tflite" if p.endswith(".tflite") else "tensorflow"
        except Exception:
            kind = "unknown"
        return "basic-pitch/" + kind
    except ImportError:
        return "pyin (monophonic fallback only)"


def _basic_pitch(path: str, role: str, mode: str) -> list[dict]:
    from basic_pitch.inference import predict
    fmin, fmax = FREQ_RANGE.get(role, (None, None))
    kw = dict(onset_threshold=0.5, frame_threshold=0.3, minimum_note_length=60.0)
    if fmin:
        kw.update(minimum_frequency=fmin, maximum_frequency=fmax)
    _, _, events = predict(path, **kw)
    return [{"start_s": float(s), "end_s": float(e), "pitch": int(p), "confidence": float(a)} for s, e, p, a, *_ in events]


def _pyin(y: np.ndarray, sr: int, role: str) -> list[dict]:
    import librosa
    fmin, fmax = FREQ_RANGE.get(role, (65.0, 1000.0))
    hop = 512
    f0, voiced, prob = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=sr, hop_length=hop)
    midi = np.where(voiced & ~np.isnan(f0), np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0))), -1).astype(int)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0][: len(midi)]
    notes, i, t = [], 0, librosa.frames_to_time(np.arange(len(midi) + 1), sr=sr, hop_length=hop)
    while i < len(midi):
        if midi[i] < 0:
            i += 1
            continue
        j = i
        while j + 1 < len(midi) and midi[j + 1] == midi[i]:
            j += 1
        notes.append({"start_s": float(t[i]), "end_s": float(t[j + 1]), "pitch": int(midi[i]),
                      "confidence": float(np.mean(prob[i:j + 1])),
                      "level": float(np.mean(rms[i:j + 1]))})
        i = j + 1
    return notes


def make_mono(notes: list[dict]) -> list[dict]:
    """Bass/melody are single-voice: when notes overlap keep the more confident one (trim, don't stack)."""
    notes = sorted(notes, key=lambda n: (n["start_s"], -n["confidence"]))
    out: list[dict] = []
    for n in notes:
        if out and n["start_s"] < out[-1]["end_s"] - 1e-3:
            if n["confidence"] > out[-1]["confidence"] and n["start_s"] - out[-1]["start_s"] > 0.04:
                out[-1]["end_s"] = n["start_s"]
                out.append(dict(n))
            elif n["start_s"] - out[-1]["start_s"] <= 0.04 and n["confidence"] > out[-1]["confidence"]:
                out[-1] = dict(n)
            # else: drop the weaker overlapping note
        else:
            out.append(dict(n))
    return out


def transcribe(path: str, y: np.ndarray, sr: int, role: str, mode: str):
    """Returns (notes_in_seconds, backend, warnings)."""
    warnings: list[str] = []
    try:
        notes = _basic_pitch(path, role, mode)
        backend = backend_name()
    except ImportError:
        if mode == "poly":
            return [], backend_name(), ["no polyphonic backend installed (pip install basic-pitch); stem NOT transcribed, nothing invented"]
        notes = _pyin(y, sr, role)
        backend = "pyin"
        warnings.append("basic-pitch not installed: used pyin monophonic fallback (lower accuracy)")
    if mode == "mono":
        notes = make_mono(notes)
    return notes, backend, warnings
