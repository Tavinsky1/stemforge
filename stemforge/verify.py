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


HOP = 512


def stem_f0(y: np.ndarray, sr: int, role: str) -> dict:
    """Frame-level f0 of a single-voice stem (pyin). Computed once, scored against any transcription."""
    import librosa
    from .analyze import pitched
    fmin, fmax = pitched.FREQ_RANGE.get(role, (65.0, 1000.0))
    f0, voiced, _ = librosa.pyin(y, fmin=max(fmin, 30.0), fmax=fmax, sr=sr, hop_length=HOP)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0][: len(f0)]
    ok = voiced & ~np.isnan(f0) & (rms > 0.1 * np.percentile(rms, 95))
    midi = np.where(ok, librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0)), np.nan)
    return {"midi": midi, "sr": sr}


def frame_scores(f0: dict, notes: list[dict], grid: BeatGrid) -> dict:
    """Frame-level agreement between a stem's f0 track and the MIDI note sounding in each frame.

    recall:       of the frames where the stem holds a clear pitch, how many have any note sounding
    precision:    of the frames with a note sounding, how many hold a clear pitch in the stem
    pitch_exact:  of frames with both, how many agree within half a semitone
    pitch_class:  same, but octave-folded (the gap to pitch_exact is octave errors)
    """
    midi = f0["midi"]
    n_fr = len(midi)
    sounding = np.full(n_fr, -1, dtype=int)
    t = lambda b: float(grid.to_time(b))
    for n in sorted(notes, key=lambda n: n["start"]):
        a = int(round(t(n["start"]) * f0["sr"] / HOP))
        b = int(round(t(n["start"] + n["duration"]) * f0["sr"] / HOP))
        if b > a and a < n_fr:
            sounding[max(a, 0):min(b, n_fr)] = n["pitch"]
    has_f0 = ~np.isnan(midi)
    has_note = sounding >= 0
    both = has_f0 & has_note
    d = np.abs(midi[both] - sounding[both])
    pc = np.abs(((midi[both] - sounding[both] + 6) % 12) - 6)
    r = lambda x: round(float(x), 3)
    return {"frame_recall": r(both.sum() / max(has_f0.sum(), 1)),
            "frame_precision": r(both.sum() / max(has_note.sum(), 1)),
            "pitch_exact": r((d < 0.5).mean()) if both.any() else 0.0,
            "pitch_class": r((pc < 0.5).mean()) if both.any() else 0.0,
            "f0_frames": int(has_f0.sum())}


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
        if s["mode"] == "mono":
            item.update(frame_scores(stem_f0(y, sr, s["role"]), tr["notes"], grid))
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
    if it["onset_recall"] < 0.5 and "frame_recall" not in it:   # sustained stems: the frame-level score is the fair one
        v.append("misses many audio onsets (recall %.2f): notes are probably missing" % it["onset_recall"])
    if it["onset_precision"] < 0.5:
        v.append("many MIDI notes have no audio onset behind them (precision %.2f): likely false notes" % it["onset_precision"])
    if not drums and it.get("pitch_class_cosine", 1) < 0.8:
        v.append("pitch content differs from the stem (cosine %.2f): wrong notes or wrong octave/key likely" % it["pitch_class_cosine"])
    if not drums and it["coverage"] < 0.6:
        v.append("only %.0f%% of audible passages have notes: sustained parts may be missing" % (it["coverage"] * 100))
    if "frame_recall" in it:
        if it["frame_recall"] < 0.6:
            v.append("only %.0f%% of the stem's pitched frames have a note sounding (frame level): notes really are missing" % (it["frame_recall"] * 100))
        if it["pitch_class"] - it["pitch_exact"] > 0.15:
            v.append("%.0f%% of matched frames are the right note in the wrong octave" % ((it["pitch_class"] - it["pitch_exact"]) * 100))
        elif it["pitch_exact"] < 0.7:
            v.append("only %.0f%% of matched frames have the right pitch" % (it["pitch_exact"] * 100))
    return v or ["no objective problem found (still check by ear)"]


def below_floor(it: dict) -> str | None:
    """Reason a stem should be left out of a build, or None. Deliberately blunt: only clear failures."""
    if it.get("status"):
        return "no notes transcribed"
    if it["onset_precision"] < 0.2:
        return "most notes have no audio behind them (onset precision %.2f): likely false notes" % it["onset_precision"]
    if it["coverage"] < 0.1:
        return "almost nothing audible is transcribed (coverage %.0f%%)" % (it["coverage"] * 100)
    return None


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
        if "frame_recall" in it:
            lines.append("   frames: recall %.2f precision %.2f | pitch exact %.2f, octave-folded %.2f" % (
                it["frame_recall"], it["frame_precision"], it["pitch_exact"], it["pitch_class"]))
        for v in it["verdict"]:
            lines.append("   - " + v)
        for w in it["warnings"]:
            lines.append("   ! " + w)
    lines += ["", "LISTEN FOR: bass octave and note lengths; kick/snare/hat mix-ups (hat vs snare especially);",
              "chords that sound thinner or busier than the original; section boundaries one bar early/late."]
    return "\n".join(lines)
