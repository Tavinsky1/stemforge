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
        return ("Cannot reach Ableton. Open Live 12, select Stemforge as a Control Surface (Preferences > Link, Tempo & MIDI), "
                "then press 'Connect to Ableton'. You can also export .mid files instead.")
    if isinstance(exc, RuntimeError) and "no audio files" in str(exc):
        return "No audio files were found in that folder. Choose the folder that holds one file per stem."
    if isinstance(exc, ValueError):
        return "Something in the analysis did not add up (%s). Open 'Show details' and send me that text." % exc
    return "Something went wrong (%s). Open 'Show details' for the technical message." % type(exc).__name__


# ---- idea + compose (the CLI's `stemforge idea` / `stemforge compose`, same code)
def idea_path(folder: str) -> str:
    return str(blueprint_path(folder))[:-len(".blueprint.json")] + ".idea.json"


def generated_path(folder: str) -> str:
    return str(blueprint_path(folder))[:-len(".blueprint.json")] + ".generated.blueprint.json"


def read_idea(bp: dict, folder: str, log) -> dict:
    """Measure the song's idea and save it next to the blueprint (.idea.json for editing, .idea.md to read)."""
    import json
    from pathlib import Path
    from .. import idea as idea_mod
    log("reading the key colour, swing and where each layer hits (about a minute)...")
    i = idea_mod.extract(bp, log=log)
    p = Path(idea_path(folder))
    p.write_text(json.dumps(i, indent=1))
    p.with_suffix(".md").write_text(idea_mod.to_markdown(i))
    log("saved %s" % p.name)
    return i


def compose_parts(bp: dict, idea: dict, seed: int, straight: bool, bed: bool, folder: str, log) -> tuple[dict, dict, str]:
    """Write new Keys/Synth. Returns (generated blueprint, rule report, path it was saved to)."""
    from .. import blueprint, compose
    log("writing new Keys and Synth (take %d)..." % seed)
    gen = compose.compose(bp, idea, seed=seed, swing_pct=50.0 if straight else None, intro_bed=bed)
    path = generated_path(folder)
    blueprint.save(gen, path)
    for r in compose.RULES:
        log("rule: " + r)
    return gen, compose.report(gen, idea), path


def idea_summary(idea: dict) -> list[str]:
    """What the idea says, in plain English, for the window."""
    from ..idea import production_notes
    k, g = idea["key"], idea["groove"]
    out = []
    colour = ", ".join(k.get("colour_tones") or []) or "none beyond the overtones"
    if k.get("has_clear_third"):
        out.append("Key: %s, with a steady third in the sustained material." % k["tonic"])
    else:
        out.append("Key: a %s drone with an open fifth (%s). There is no steady third, so it is neither major nor minor. "
                   "Colour tone: %s." % (k["tonic"], k["palette_ranked"][1] if len(k["palette_ranked"]) > 1 else "A", colour))
    said = k.get("analyzer_said") or {}
    if said.get("tonic"):
        out.append("The analyzer's first guess was %s %s (confidence %.2f); the audio measurement is used instead."
                   % (said["tonic"], said.get("mode", ""), said.get("confidence", 0.0)))
    out.append("Swing: %.0f%% on the 16th notes (50%% would be straight). Tempo %.1f BPM, %d bars."
               % (g["swing_pct"], idea["tempo"], idea["bars"]))
    out.extend(production_notes(idea["tempo"], k["tonic"])[:2])
    return out
