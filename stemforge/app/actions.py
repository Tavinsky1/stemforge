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


def plain_error(exc: BaseException) -> str:
    """One plain-English sentence for the window. The technical detail goes to 'Show details'."""
    if isinstance(exc, ImportError):
        return ("A part Stemforge needs is not installed (%s). Reinstall with: pip install -e \".[app,pitched]\" "
                "using Python 3.11." % (getattr(exc, "name", None) or exc))
    if isinstance(exc, FileNotFoundError):
        return "Stemforge could not find a file it needs: %s" % (exc.filename or exc)
    if isinstance(exc, PermissionError):
        return "Stemforge is not allowed to read or write there (%s). Check the folder's permissions." % (exc.filename or exc)
    if isinstance(exc, MemoryError):
        return "The computer ran out of memory while analysing. Close other apps, or analyse fewer stems at a time."
    if isinstance(exc, (ConnectionRefusedError, TimeoutError, ConnectionError)):
        return ("Cannot reach Ableton. Open Live 12, select AbletonMCP as a Control Surface, then press "
                "'Connect to Ableton'. You can also export .mid files instead.")
    if isinstance(exc, RuntimeError) and "no audio files" in str(exc):
        return "No audio files were found in that folder. Choose the folder that holds one file per stem."
    if isinstance(exc, ValueError):
        return "Something in the analysis did not add up (%s). Open 'Show details' and send me that text." % exc
    return "Something went wrong (%s). Open 'Show details' for the technical message." % type(exc).__name__
