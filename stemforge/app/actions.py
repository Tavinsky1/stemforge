"""What the buttons do. The build/selection logic is shared with the CLI in stemforge.workflow."""
from __future__ import annotations

from ..discover import ROLE_MODE, Stem, discover
from ..verify import below_floor
from ..workflow import blueprint_path, run_build, save_verify, select_stems  # noqa: F401  (re-exported)

ROLES = sorted(ROLE_MODE)


def analyze_folder(folder: str, stems: list[Stem], log) -> tuple[dict, dict]:
    """Analyze + verify. Saves the blueprint and verify report next to the stems (same files the CLI writes)."""
    from .. import blueprint
    from ..analyze.pipeline import analyze
    from ..verify import verify
    bp = analyze(folder, stems, log=log)
    path = blueprint_path(folder)
    blueprint.save(bp, path)
    log("checking the transcription against the stems...")
    rep = verify(bp)
    save_verify(path, rep)
    return bp, rep


def quality(item: dict) -> tuple[str, str]:
    """(label, detail) where label is one of ok / check / out."""
    reason = below_floor(item)
    if reason:
        return "out", reason
    v = item.get("verdict", [])
    if v and not v[0].startswith("no objective"):
        return "check", v[0]
    return "ok", "no objective problem found (still check by ear)"


def stems_from_folder(folder: str) -> list[Stem]:
    return discover(folder)


def make_stem(s: Stem, role: str) -> Stem:
    return Stem(name=s.name, path=s.path, role=role, mode=ROLE_MODE[role])
