"""stemforge CLI: discover | analyze | verify | clips | build."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import blueprint


def _cmd_discover(a):
    from .discover import discover
    from .analyze import pitched
    stems = discover(a.folder)
    for s in stems:
        print("%-30s role=%-8s mode=%-6s %s" % (s.name, s.role, s.mode, s.path))
    print("\npython %s | ffmpeg: %s | pitched backend: %s" % (sys.version.split()[0], shutil.which("ffmpeg") or "NOT FOUND",
                                                            pitched.backend_name()))
    for mod in ("numpy", "librosa", "soundfile", "mido", "basic_pitch"):
        try:
            m = __import__(mod)
            print("  %-12s %s" % (mod, getattr(m, "__version__", "installed")))
        except ImportError:
            print("  %-12s MISSING" % mod)


def _cmd_analyze(a):
    from .analyze.pipeline import analyze
    from .discover import discover
    stems = discover(a.folder)
    if a.skip:
        stems = [s for s in stems if s.name not in a.skip and s.role not in a.skip]
    bp = analyze(a.folder, stems, resolution=a.resolution, strength=a.strength, min_confidence=a.min_confidence)
    out = a.out or str(Path(a.folder) / (Path(a.folder).name + ".blueprint.json"))
    blueprint.save(bp, out)
    g = bp["global"]
    print("\nblueprint -> %s" % out)
    print("tempo %.2f | key %s | %d bars | %d sections | %d clips" % (
        g["tempo"], "%s %s (conf %.2f)" % (g["key"]["tonic"], g["key"]["mode"], g["key"]["confidence"]) if g["key"] else "n/a",
        g["n_bars"], len(bp["sections"]), len(bp["clips"])))
    for s in bp["sections"]:
        ev = "; ".join("%s %s" % (e["stem"], e["event"]) for e in s["evidence"] if "stem" in e) or "-"
        print("  %-22s bar %-3d %s" % (s["name"], s["start_bar"] + 1, ev))
    for w in bp["warnings"]:
        print("WARNING:", w)
    for s in bp["stems"]:
        for w in s["transcription"]["warnings"]:
            print("WARNING [%s]: %s" % (s["name"], w))


def _cmd_verify(a):
    from .verify import verify, format_report
    bp = blueprint.load(a.blueprint)
    rep = verify(bp)
    print(format_report(rep))


def _cmd_clips(a):
    from .analyze.clips import derive_clips
    bp = blueprint.load(a.blueprint)
    derive_clips(bp, a.min_confidence)
    blueprint.save(bp, a.out or a.blueprint)
    print("%d clips, %d placements (min confidence %.2f)" % (len(bp["clips"]), len(bp["placements"]), a.min_confidence))


def _cmd_build(a):
    from .build.backends import DryRunBackend, LiveBackend, MidiFilesBackend, NotSupported, build, compare_notes
    from .build.plan import make_plan
    bp = blueprint.load(a.blueprint)
    plan = make_plan(bp, a.mode, a.stems)
    roles = {s["name"]: s["role"] for s in bp["stems"]}
    if a.backend == "dry":
        backend = DryRunBackend()
    elif a.backend == "midi":
        backend = MidiFilesBackend(a.out, bp["song"]["name"])
    else:
        backend = LiveBackend(port=a.port)
    try:
        res = build(plan, backend, roles)
    except NotSupported as e:
        print("NOT SUPPORTED:", e)
        return 2
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        print("Cannot reach Live on port %d (%s). Open Live 12 with the AbletonMCP Control Surface selected "
              "(Preferences > Link/Tempo/MIDI), or use --backend dry / midi." % (a.port, e))
        return 3
    print("done: %d tracks, %d clips, %d notes" % (len(res["tracks"]), res["clips"], res["notes"]))
    if a.backend == "live" and a.readback and plan.mode == "session":
        bad = 0
        for stem, sec, cid, *_ in plan.placements:
            r = compare_notes(plan.clips[cid]["notes"], backend.read_back(res["tracks"][stem], res["scenes"][sec]))
            if not r["match"]:
                bad += 1
                print("MISMATCH %s scene %d: expected %d got %d, missing %d extra %d" % (stem, sec, r["expected"], r["got"], len(r["missing"]), len(r["extra"])))
        print("read-back: %d/%d clips match" % (len(plan.placements) - bad, len(plan.placements)))
        return 1 if bad else 0
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="stemforge")
    sp = p.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("discover"); d.add_argument("folder"); d.set_defaults(fn=_cmd_discover)
    an = sp.add_parser("analyze"); an.add_argument("folder"); an.add_argument("--out")
    an.add_argument("--skip", nargs="*", help="stem names or roles to leave out, e.g. vocals fx")
    an.add_argument("--resolution", type=float, default=0.25, help="quantize grid in beats (0.25 = 16th)")
    an.add_argument("--strength", type=float, default=1.0, help="1 = snap to grid, 0 = keep raw timing")
    an.add_argument("--min-confidence", type=float, default=0.0); an.set_defaults(fn=_cmd_analyze)
    v = sp.add_parser("verify"); v.add_argument("blueprint"); v.set_defaults(fn=_cmd_verify)
    c = sp.add_parser("clips"); c.add_argument("blueprint"); c.add_argument("--min-confidence", type=float, required=True)
    c.add_argument("--out"); c.set_defaults(fn=_cmd_clips)
    b = sp.add_parser("build"); b.add_argument("blueprint")
    b.add_argument("--mode", choices=["session", "arrangement"], default="session")
    b.add_argument("--backend", choices=["dry", "midi", "live"], default="dry")
    b.add_argument("--out", default="out"); b.add_argument("--port", type=int, default=9877)
    b.add_argument("--stems", nargs="*"); b.add_argument("--readback", action="store_true")
    b.set_defaults(fn=_cmd_build)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
