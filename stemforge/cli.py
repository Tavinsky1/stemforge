"""stemforge CLI: discover | analyze | verify | clips | build."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import blueprint
from .build.backends import DEFAULT_PORT


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
    from .workflow import blueprint_path
    out = a.out or str(blueprint_path(a.folder))
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
    from .workflow import save_verify
    print("\nreport saved -> %s (build uses it to leave out stems that clearly failed)" % save_verify(a.blueprint, rep))


def _cmd_clips(a):
    from .analyze.clips import derive_clips
    bp = blueprint.load(a.blueprint)
    derive_clips(bp, a.min_confidence)
    blueprint.save(bp, a.out or a.blueprint)
    print("%d clips, %d placements (min confidence %.2f)" % (len(bp["clips"]), len(bp["placements"]), a.min_confidence))


def _cmd_build(a):
    from . import workflow
    from .build.backends import NotSupported
    bp = blueprint.load(a.blueprint)
    report = workflow.load_verify(a.blueprint)
    if report is None:
        print("note: no verify report next to the blueprint; run `stemforge verify` first to auto-exclude failed stems")
    try:
        s = workflow.run_build(bp, report, mode=a.mode, target={"dry": "preview", "midi": "midi", "live": "live"}[a.backend],
                               out_dir=a.out, set_tempo=a.set_tempo, include=set(a.include or []), only=a.stems,
                               port=a.port, readback=a.readback)
    except NotSupported as e:
        print("NOT SUPPORTED:", e)
        return 2
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        print("Cannot reach Live on port %d (%s). Open Live 12 with the Stemforge Control Surface selected "
              "(Preferences > Link, Tempo & MIDI), or use --backend dry / midi." % (a.port, e))
        return 3
    print("done: %d tracks, %d clips, %d notes" % (s["tracks"], s["clips"], s["notes"]))
    if s["readback"]:
        ok, total = s["readback"]
        print("read-back: %d/%d clips match" % (ok, total))
        return 0 if ok == total else 1
    return 0


def _cmd_import_midi(a):
    from .importmidi import import_into_blueprint
    bp = blueprint.load(a.blueprint)
    try:
        r = import_into_blueprint(bp, a.stem, a.midi, as_beats=a.as_beats, min_confidence=a.min_confidence)
    except ValueError as e:
        print("ERROR:", e)
        return 2
    blueprint.save(bp, a.out or a.blueprint)
    print("imported %d notes into '%s'; %d clips in the blueprint now. Run `stemforge verify` to compare against the stem."
          % (r["notes"], r["stem"], r["clips"]))


def _cmd_smoke(a):
    if not a.confirm_set_ok:
        print("Refusing to connect to Live: pass --confirm-set-ok once you are happy for the open set to get one "
              "new MIDI track and one new scene named 'stemforge_smoke' (nothing existing is touched; use a scratch set the first time).")
        return 2
    from .smoke import run
    try:
        report = run(port=a.port)
    except OSError as e:
        print("Cannot reach Live on port %d (%s). Open Live 12 with the Stemforge Control Surface selected." % (a.port, e))
        return 3
    return 0 if report["ok"] else 1


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
    b.add_argument("--out", default="out"); b.add_argument("--port", type=int, default=DEFAULT_PORT)
    b.add_argument("--stems", nargs="*"); b.add_argument("--readback", action="store_true")
    b.add_argument("--include", nargs="*", help="stems to build even though verify says they failed")
    b.add_argument("--set-tempo", action="store_true", help="change the open Live set's tempo to the song's (never done by default)")
    b.set_defaults(fn=_cmd_build)
    im = sp.add_parser("import-midi", help="use a MIDI file (NeuralNote, DAW, hand-edited) as one stem's notes")
    im.add_argument("blueprint"); im.add_argument("midi"); im.add_argument("--stem", required=True)
    im.add_argument("--as-beats", action="store_true",
                    help="MIDI bar/beat positions already match the song's bar 1 (default: positions are time from the stem start)")
    im.add_argument("--min-confidence", type=float, default=0.0); im.add_argument("--out")
    im.set_defaults(fn=_cmd_import_midi)
    sm = sp.add_parser("smoke-live", help="write/read-back check against a SCRATCH Live set (adds one track)")
    sm.add_argument("--port", type=int, default=DEFAULT_PORT)
    sm.add_argument("--confirm-set-ok", "--confirm-scratch", dest="confirm_set_ok", action="store_true",
                    help="required: you confirm it is fine to add a test track and scene to the open Live set "
                         "(use a scratch set for the first run)")
    sm.set_defaults(fn=_cmd_smoke)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
