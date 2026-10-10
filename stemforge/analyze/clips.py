"""Turn per-stem notes + sections into reusable clips (identical content -> one clip)."""
from __future__ import annotations

import hashlib
import json

from .grid import BEATS_PER_BAR


def _sig(notes: list[dict]) -> str:
    key = [(n["pitch"], round(n["start"], 3), round(n["duration"], 3), n["velocity"]) for n in notes]
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:10]


def find_period(bar_notes: list[list[dict]], candidates=(1, 2, 4, 8), min_jaccard: float = 0.9):
    """Smallest period p (in bars) such that every bar matches bar i%p (Jaccard on pitch@slot). None if no loop."""
    def key(notes, off):
        return {(n["pitch"], round((n["start"] - off) * 4)) for n in notes}
    n = len(bar_notes)
    keys = [key(b, i * BEATS_PER_BAR) for i, b in enumerate(bar_notes)]
    for p in candidates:
        if p >= n or n % p:
            continue
        ok = True
        for i in range(p, n):
            a, b = keys[i], keys[i % p]
            u = len(a | b)
            if u and len(a & b) / u < min_jaccard:
                ok = False
                break
        if ok:
            return p
    return None


def derive_clips(bp: dict, min_confidence: float = 0.0) -> None:
    clips: dict[str, dict] = {}
    placements: list[dict] = []
    for stem in bp["stems"]:
        tr = stem["transcription"]
        if tr.get("skipped") or not tr["notes"]:
            continue
        notes = [n for n in tr["notes"] if n["confidence"] >= min_confidence]
        for sec in bp["sections"]:
            b0 = sec["start_bar"] * BEATS_PER_BAR
            length = sec["length_bars"] * BEATS_PER_BAR
            sub = []
            for n in notes:
                if b0 <= n["start"] < b0 + length:
                    d = min(n["duration"], b0 + length - n["start"])
                    sub.append({"pitch": n["pitch"], "start": round(n["start"] - b0, 4), "duration": round(d, 4),
                                "velocity": n["velocity"], "confidence": n["confidence"]})
            if not sub:
                continue
            cid = "%s-%s" % (stem["name"], _sig(sub))
            if cid not in clips:
                bars = [[n for n in sub if i * 4 <= n["start"] < (i + 1) * 4] for i in range(sec["length_bars"])]
                clips[cid] = {"id": cid, "stem": stem["name"], "name": "%s %s" % (stem["name"], sec["label"]),
                              "length_beats": float(length), "notes": sub,
                              "loop_period_bars": find_period(bars), "used_in": []}
            clips[cid]["used_in"].append(sec["index"])
            placements.append({"section": sec["index"], "stem": stem["name"], "clip": cid})
    bp["clips"] = list(clips.values())
    bp["placements"] = placements
    bp["clip_min_confidence"] = min_confidence
