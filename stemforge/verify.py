"""Phase 1 verification: render the transcription to sine/click audio and compare with each stem."""
from __future__ import annotations

import numpy as np

from .analyze import audio
from .analyze.grid import BeatGrid


def render(notes: list[dict], grid: BeatGrid, sr: int, n_samples: int, drums: bool) -> np.ndarray:
    out = np.zeros(n_samples, dtype=np.float32)
    for n in notes:
        t0 = float(grid.to_time(n["start"]))
        t1 = float(grid.to_time(n["start"] + n["duration"]))
        a, b = int(t0 * sr), min(int(t1 * sr), n_samples)
        if a < 0 or a >= n_samples or b <= a:
            continue
        amp = n["velocity"] / 127.0 * 0.3
        if drums:
            m = min(int(0.03 * sr), n_samples - a)
            rng = np.random.default_rng(n["pitch"])
            out[a:a + m] += (rng.standard_normal(m) * np.linspace(1, 0, m) * amp).astype(np.float32)
        else:
            f = 440.0 * 2 ** ((n["pitch"] - 69) / 12)
            tt = np.arange(b - a) / sr
            env = np.minimum(1, tt * 200) * np.minimum(1, (tt[::-1] + 1e-3) * 100)
            out[a:b] += (np.sin(2 * np.pi * f * tt) * env * amp).astype(np.float32)
    return out


def _onset_f1(ref_t: np.ndarray, est_t: np.ndarray, tol: float = 0.06):
    if len(ref_t) == 0 or len(est_t) == 0:
        return 0.0, 0.0, 0.0
    used, hit = set(), 0
    for r in ref_t:
        j = int(np.argmin(np.abs(est_t - r)))
        if abs(est_t[j] - r) <= tol and j not in used:
            used.add(j)
            hit += 1
    p, r_ = hit / len(est_t), hit / len(ref_t)
    return p, r_, (2 * p * r_ / (p + r_) if p + r_ else 0.0)


def verify(bp: dict, log=print) -> dict:
    import librosa
    sr = audio.SR
    grid = BeatGrid(np.array(bp["global"]["beats_s"]))
    rep = {"stems": {}}
    for s in bp["stems"]:
        tr = s["transcription"]
        if tr.get("skipped") or not tr["notes"]:
            rep["stems"][s["name"]] = {"status": "no notes", "warnings": tr.get("warnings", [])}
            continue
        y = audio.load_mono(s["path"], sr)
        drums = s["mode"] == "drums"
        r = render(tr["notes"], grid, sr, len(y), drums)
        ref_on = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        est_on = np.array(sorted({float(grid.to_time(n["start"])) for n in tr["notes"]}))
        p, rc, f1 = _onset_f1(ref_on, est_on)
        item = {"onset_precision": round(p, 3), "onset_recall": round(rc, 3), "onset_f1": round(f1, 3),
                "notes": len(tr["notes"]), "warnings": tr.get("warnings", [])}
        if not drums:
            c = librosa.feature.chroma_cqt(y=librosa.effects.harmonic(y), sr=sr).mean(axis=1)
            h = np.zeros(12)
            for n in tr["notes"]:
                h[n["pitch"] % 12] += n["duration"]
            cos = float(np.dot(c, h) / (np.linalg.norm(c) * np.linalg.norm(h) + 1e-9))
            item["pitch_class_cosine"] = round(cos, 3)
        rms = librosa.feature.rms(y=y)[0]
        rr = librosa.feature.rms(y=r)[0]
        n_f = min(len(rms), len(rr))
        act = rms[:n_f] > 0.1 * np.percentile(rms, 95)
        item["coverage"] = round(float((rr[:n_f][act] > 1e-4).mean()) if act.any() else 0.0, 3)
        item["verdict"] = _verdict(item, drums)
        rep["stems"][s["name"]] = item
    return rep


def _verdict(it: dict, drums: bool) -> list[str]:
    v = []
    if it["onset_recall"] < 0.5:
        v.append("misses many audio onsets (recall %.2f): notes are probably missing" % it["onset_recall"])
    if it["onset_precision"] < 0.5:
        v.append("many MIDI notes have no audio onset behind them (precision %.2f): likely false notes" % it["onset_precision"])
    if not drums and it.get("pitch_class_cosine", 1) < 0.8:
        v.append("pitch content differs from the stem (cosine %.2f): wrong notes or wrong octave/key likely" % it["pitch_class_cosine"])
    if not drums and it["coverage"] < 0.6:
        v.append("only %.0f%% of audible passages have notes: sustained parts may be missing" % (it["coverage"] * 100))
    return v or ["no objective problem found (still check by ear)"]


def format_report(rep: dict) -> str:
    lines = ["VERIFICATION (objective checks only; I cannot hear audio)", ""]
    for name, it in rep["stems"].items():
        lines.append("== %s" % name)
        if it.get("status"):
            lines.append("   %s %s" % (it["status"], "; ".join(it["warnings"])))
            continue
        lines.append("   onsets: precision %.2f recall %.2f F1 %.2f | coverage %.0f%%%s" % (
            it["onset_precision"], it["onset_recall"], it["onset_f1"], it["coverage"] * 100,
            " | pitch-class cosine %.2f" % it["pitch_class_cosine"] if "pitch_class_cosine" in it else ""))
        for v in it["verdict"]:
            lines.append("   - " + v)
        for w in it["warnings"]:
            lines.append("   ! " + w)
    lines += ["", "LISTEN FOR: bass octave and note lengths; kick/snare/hat mix-ups (hat vs snare especially);",
              "chords that sound thinner or busier than the original; section boundaries one bar early/late."]
    return "\n".join(lines)
