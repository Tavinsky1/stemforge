"""Phase 0: find stem files and decide what each one is."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXT = {".wav", ".mp3", ".flac", ".aif", ".aiff", ".ogg", ".m4a"}

# (role, regex on lower-case file stem). First match wins, so order matters.
_ROLE_PATTERNS = [
    ("kick", r"\bkick|\bbd\b|bassdrum"),
    ("snare", r"snare|\bclap|\bsd\b"),
    ("hat", r"hi.?hat|\bhats?\b|\bhh\b|cymbal"),
    ("drums", r"drum|perc|beat|rhythm"),
    ("bass", r"bass|\bsub\b|808"),
    ("vocals", r"vocal|\bvox\b|voice|choir|sing"),
    ("guitar", r"guitar|gtr"),
    ("keys", r"piano|keys|organ|rhodes|keyboard"),
    ("strings", r"string|violin|cello"),
    ("synth", r"synth|lead|pad|arp|pluck|chord"),
    ("fx", r"\bfx\b|effect|noise|riser|sweep|atmos|ambien"),
]

# How each role is transcribed. "poly"/"mono" need a pitched backend; drums use onsets.
ROLE_MODE = {
    "kick": "drums", "snare": "drums", "hat": "drums", "drums": "drums",
    "bass": "mono", "vocals": "mono", "guitar": "poly", "keys": "poly",
    "strings": "poly", "synth": "poly", "other": "poly", "fx": "skip",
}


@dataclass
class Stem:
    name: str
    path: str
    role: str
    mode: str


def classify(file_stem: str) -> str:
    s = file_stem.lower().replace("_", " ").replace("-", " ")
    for role, pat in _ROLE_PATTERNS:
        if re.search(pat, s):
            return role
    return "other"


def discover(folder: str | Path) -> list[Stem]:
    folder = Path(folder)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT and not p.name.startswith("."))
    stems = []
    for p in files:
        role = classify(p.stem)
        stems.append(Stem(name=p.stem, path=str(p), role=role, mode=ROLE_MODE[role]))
    return stems
