"""The song blueprint: the JSON contract between the analyzer and the builder."""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = 1


def save(bp: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(bp, indent=1))


def load(path: str | Path) -> dict:
    bp = json.loads(Path(path).read_text())
    validate(bp)
    return bp


def validate(bp: dict) -> None:
    if bp.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported blueprint schema_version %r" % bp.get("schema_version"))
    for key in ("global", "sections", "stems", "clips", "placements"):
        if key not in bp:
            raise ValueError("blueprint missing %r" % key)
    clip_ids = {c["id"] for c in bp["clips"]}
    for p in bp["placements"]:
        if p["clip"] not in clip_ids:
            raise ValueError("placement references unknown clip %r" % p["clip"])
    for c in bp["clips"]:
        for n in c["notes"]:
            if not (0 <= n["pitch"] <= 127 and 1 <= n["velocity"] <= 127 and n["duration"] > 0 and n["start"] >= 0):
                raise ValueError("bad note in clip %s: %r" % (c["id"], n))
            if n["start"] + n["duration"] > c["length_beats"] + 1e-6:
                raise ValueError("note exceeds clip length in %s: %r" % (c["id"], n))
