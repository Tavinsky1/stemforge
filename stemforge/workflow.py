"""Shared by the CLI and the desktop app: where files live, which stems get built, running a build."""
from __future__ import annotations

import json
from pathlib import Path

from .build.backends import DryRunBackend, LiveBackend, MidiFilesBackend, build, compare_notes
from .build.plan import make_plan
from .verify import below_floor


def blueprint_path(folder: str | Path) -> Path:
    return Path(folder) / (Path(folder).name + ".blueprint.json")


def verify_path(blueprint_file: str | Path) -> Path:
    return Path(str(blueprint_file).replace(".blueprint.json", "") + ".verify.json")


def save_verify(blueprint_file: str | Path, rep: dict) -> Path:
    p = verify_path(blueprint_file)
    p.write_text(json.dumps(rep, indent=1))
    return p


def load_verify(blueprint_file: str | Path) -> dict | None:
    """Per-stem verify results saved next to the blueprint, or None when verify has not been run."""
    p = verify_path(blueprint_file)
    return json.loads(p.read_text())["stems"] if p.exists() else None


def select_stems(bp: dict, report: dict | None, include=(), only=None) -> tuple[list[str], dict[str, str]]:
    """Which stems get built. Returns (kept, {left_out_name: reason}).

    Left out: stems skipped at analysis, and (when a verify report exists) stems that clearly failed it.
    `include` forces a stem back in; `only` restricts the choice to the named stems.
    """
    keep: list[str] = []
    out: dict[str, str] = {}
    for s in bp["stems"]:
        n = s["name"]
        if only is not None and n not in only:
            continue
        tr = s.get("transcription", {})
        if tr.get("skipped"):
            reason = tr.get("reason") or "skipped"
        elif report is None:
            reason = None if tr.get("notes", True) else "no notes transcribed"
        else:
            item = report.get(n)
            reason = below_floor(item) if item else "not checked"
        if reason and n not in include:
            out[n] = reason
        else:
            keep.append(n)
    return keep, out


def run_build(bp: dict, report: dict | None, *, mode: str = "session", target: str = "preview", out_dir: str = "out",
              set_tempo: bool = False, include=(), only=None, port: int = 9877, readback: bool = True,
              log=print) -> dict:
    """target: preview | midi | live. Raises NotSupported (plain message) when the target cannot do this build.

    Live builds only add new tracks and scenes, leave the set's tempo alone unless set_tempo, and (with
    readback) read every clip's notes back from Live and compare them with the plan.
    """
    keep, excluded = select_stems(bp, report, include, only)
    for n, why in excluded.items():
        log("EXCLUDED %s: %s (force with --include \"%s\")" % (n, why, n))
    plan = make_plan(bp, mode, keep)
    roles = {s["name"]: s["role"] for s in bp["stems"]}
    if target == "preview":
        backend = DryRunBackend(log=log)
    elif target == "midi":
        backend = MidiFilesBackend(out_dir, bp["song"]["name"])
    elif target == "live":
        backend = LiveBackend(port=port, log=log)
    else:
        raise ValueError("target must be preview, midi or live")
    res = build(plan, backend, roles, log=log, set_tempo=set_tempo)
    summary = {"tracks": len(res["tracks"]), "clips": res["clips"], "notes": res["notes"],
               "excluded": excluded, "readback": None, "mismatches": []}
    if target == "live" and readback:
        for stem, sec, cid, start, length, name in plan.placements:
            got = (backend.read_back(res["tracks"][stem], res["scenes"][sec]) if plan.mode == "session"
                   else backend.read_back_arrangement(res["tracks"][stem], start))
            r = compare_notes(plan.clips[cid]["notes"], got)
            if not r["match"]:
                summary["mismatches"].append(name)
                log("MISMATCH %s '%s': expected %d got %d, missing %d extra %d"
                    % (stem, name, r["expected"], r["got"], len(r["missing"]), len(r["extra"])))
        total = len(plan.placements)
        summary["readback"] = (total - len(summary["mismatches"]), total)
    return summary
