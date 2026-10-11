"""What the buttons do. Thin wrappers over the same library calls the CLI uses."""
from __future__ import annotations

import json
from pathlib import Path

from .. import blueprint
from ..build.backends import DryRunBackend, LiveBackend, MidiFilesBackend, NotSupported, build, compare_notes
from ..build.plan import make_plan
from ..discover import ROLE_MODE, Stem, discover
from ..verify import below_floor

ROLES = sorted(ROLE_MODE)


def blueprint_path(folder: str) -> Path:
    return Path(folder) / (Path(folder).name + ".blueprint.json")


def analyze_folder(folder: str, stems: list[Stem], log) -> tuple[dict, dict]:
    """Analyze + verify. Saves the blueprint and verify report next to the stems (same files the CLI writes)."""
    from ..analyze.pipeline import analyze
    from ..verify import verify
    bp = analyze(folder, stems, log=log)
    path = blueprint_path(folder)
    blueprint.save(bp, path)
    log("checking the transcription against the stems...")
    rep = verify(bp)
    Path(str(path).replace(".blueprint.json", "") + ".verify.json").write_text(json.dumps(rep, indent=1))
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


def select_stems(bp: dict, report: dict, include: set[str]) -> tuple[list[str], dict[str, str]]:
    keep, out = [], {}
    for s in bp["stems"]:
        n = s["name"]
        item = report.get(n)
        reason = below_floor(item) if item else "not checked"
        if s["transcription"].get("skipped"):
            reason = s["transcription"].get("reason") or "skipped"
        if reason and n not in include:
            out[n] = reason
        else:
            keep.append(n)
    return keep, out


def run_build(bp: dict, report: dict, *, mode: str, target: str, out_dir: str, set_tempo: bool,
              include: set[str], port: int, log) -> dict:
    """target: preview | midi | live. Returns a summary dict; raises NotSupported with a plain message."""
    keep, excluded = select_stems(bp, report, include)
    plan = make_plan(bp, mode, keep)
    roles = {s["name"]: s["role"] for s in bp["stems"]}
    if target == "preview":
        backend = DryRunBackend(log=log)
    elif target == "midi":
        backend = MidiFilesBackend(out_dir, bp["song"]["name"])
    else:
        backend = LiveBackend(port=port, log=log)
    res = build(plan, backend, roles, log=log, set_tempo=set_tempo)
    summary = {"tracks": len(res["tracks"]), "clips": res["clips"], "notes": res["notes"],
               "excluded": excluded, "readback": None}
    if target == "live":
        bad = 0
        for stem, sec, cid, start, length, name in plan.placements:
            got = (backend.read_back(res["tracks"][stem], res["scenes"][sec]) if plan.mode == "session"
                   else backend.read_back_arrangement(res["tracks"][stem], start))
            if not compare_notes(plan.clips[cid]["notes"], got)["match"]:
                bad += 1
                log("MISMATCH: %s '%s'" % (stem, name))
        summary["readback"] = (len(plan.placements) - bad, len(plan.placements))
    return summary


def stems_from_folder(folder: str) -> list[Stem]:
    return discover(folder)


def make_stem(s: Stem, role: str) -> Stem:
    return Stem(name=s.name, path=s.path, role=role, mode=ROLE_MODE[role])
