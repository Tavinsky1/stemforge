"""Phase 1: stems folder -> blueprint dict."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .. import blueprint
from ..discover import Stem, discover
from . import audio, clips as clipmod, drums as drummod, grid as gridmod, key as keymod
from . import pitched, quantize as qmod, sections as secmod


def analyze(folder: str, stems: list[Stem] | None = None, resolution: float = 0.25, strength: float = 1.0,
            min_confidence: float = 0.0, log=print) -> dict:
    stems = stems or discover(folder)
    if not stems:
        raise RuntimeError("no audio files found in %s" % folder)
    sr = audio.SR
    log("loading %d stems..." % len(stems))
    ys = {s.name: audio.load_mono(s.path, sr) for s in stems}
    n_max = max(len(y) for y in ys.values())
    ys = {k: np.pad(v, (0, n_max - len(v))) for k, v in ys.items()}
    duration = n_max / sr
    warnings: list[str] = []

    rhythm = [ys[s.name] for s in stems if s.mode == "drums" or s.role == "bass"] or [ys[s.name] for s in stems]
    y_rhythm = np.sum(rhythm, axis=0)
    grid, ginfo = gridmod.detect_grid(y_rhythm, sr, duration)
    if not ginfo["steady"]:
        warnings.append("tempo drifts (up to %.2f beats off a straight grid): using tracked beats; Live will play at constant %.1f BPM so MIDI follows the beats of the audio only approximately"
                        % (ginfo["drift_beats"], ginfo["tempo"]))
    if ginfo["downbeat_confidence"] < 0.15:
        warnings.append("downbeat is a guess (%s; confidence %.2f): bar lines may be off by 1-3 beats, check bar 1 by ear"
                        % (ginfo["downbeat_method"], ginfo["downbeat_confidence"]))
    n_bars = int(np.floor(float(grid.to_beat(duration)) / gridmod.BEATS_PER_BAR + 0.1))   # full bars only
    log("tempo %.2f BPM, %d bars" % (ginfo["tempo"], n_bars))

    # key from pitched stems
    chroma = [keymod.chroma_of(ys[s.name], sr) for s in stems if s.mode in ("mono", "poly")]
    key = keymod.detect_key(np.mean(chroma, axis=0)) if chroma else None
    if key and key["confidence"] < 0.3:
        warnings.append("key is ambiguous (%s %s vs %s %s); check by ear, modal tracks (dorian etc.) are reported as the nearest major/minor"
                        % (key["tonic"], key["mode"], key["alt"]["tonic"], key["alt"]["mode"]))

    # sections
    levels = {s.name: secmod.bar_levels(ys[s.name], sr, grid, n_bars) for s in stems}
    sections = secmod.find_sections(levels)
    secmod.label_sections(sections, [s.name for s in stems if s.mode == "drums"], [s.name for s in stems if s.role == "bass"])
    log("%d sections" % len(sections))

    # transcription
    out_stems = []
    for s in stems:
        entry = {"name": s.name, "role": s.role, "path": s.path, "mode": s.mode,
                 "transcription": {"backend": None, "skipped": False, "reason": None, "warnings": [], "notes": [], "stats": {}}}
        tr = entry["transcription"]
        if s.mode == "skip":
            tr.update(skipped=True, reason="role '%s' is not transcribed" % s.role)
            out_stems.append(entry)
            continue
        t0 = time.time()
        log("transcribing %s (%s/%s)..." % (s.name, s.role, s.mode))
        if s.mode == "drums":
            fixed = {"kick": "kick", "snare": "snare", "hat": "hat"}.get(s.role)
            raw = drummod.transcribe_drums(ys[s.name], sr, fixed)
            tr["backend"] = "onset+spectral"
        else:
            raw, tr["backend"], w = pitched.transcribe(s.path, ys[s.name], sr, s.role, s.mode)
            tr["warnings"] += w
        beats = qmod.to_beats(raw, grid)
        vel_src = [n.get("level", n["confidence"]) for n in beats] if s.mode == "drums" else [n["confidence"] for n in beats]
        for n, v in zip(beats, qmod.velocity_from_level(vel_src)):
            n["velocity"] = v
        cleaned, stats = qmod.quantize(beats, resolution, strength, drums=(s.mode == "drums"), mono=(s.mode == "mono"))
        tr["stats"] = stats
        tr["notes"] = [{"pitch": n["pitch"], "start": n["start"], "duration": n["duration"],
                        "velocity": max(1, min(127, n["velocity"])), "confidence": round(float(n["confidence"]), 3),
                        **({"cls": n["cls"]} if "cls" in n else {})} for n in cleaned]
        if not tr["notes"] and not tr["warnings"]:
            tr["warnings"].append("no notes found")
        if stats.get("dropped_negative"):
            tr["warnings"].append("%d notes before the first downbeat were dropped (pickup)" % stats["dropped_negative"])
        low = sum(1 for n in tr["notes"] if n["confidence"] < 0.5)
        if low:
            tr["warnings"].append("%d of %d notes have confidence < 0.5" % (low, len(tr["notes"])))
        out_stems.append(entry)
        log("  %d notes in %.1fs" % (len(tr["notes"]), time.time() - t0))

    bp = {
        "schema_version": blueprint.SCHEMA_VERSION,
        "song": {"name": Path(folder).name, "source_dir": str(Path(folder).resolve()), "duration_s": round(duration, 2)},
        "global": {**ginfo, "n_bars": n_bars, "key": key, "beats_s": [round(float(t), 4) for t in grid.beat_times],
                   "quantize": {"resolution_beats": resolution, "strength": strength}},
        "sections": sections,
        "stems": out_stems,
        "warnings": warnings,
    }
    clipmod.derive_clips(bp, min_confidence)
    blueprint.validate(bp)
    return bp
