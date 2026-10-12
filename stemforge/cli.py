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


def _idea_path(bp_path: str) -> str:
    return bp_path[:-len(".blueprint.json")] + ".idea.json" if bp_path.endswith(".blueprint.json") else bp_path + ".idea.json"


def _cmd_idea(a):
    """Read the idea of the song (key colour, swing, structure, where the layers really hit) and save it."""
    from . import idea
    bp = blueprint.load(a.blueprint)
    i = idea.extract(bp)
    path = a.out or _idea_path(a.blueprint)
    Path(path).write_text(json.dumps(i, indent=1))
    md = Path(path).with_suffix(".md")
    md.write_text(idea.to_markdown(i))
    print(idea.to_markdown(i))
    print("saved -> %s and %s (edit the json if the reading is wrong, then run `stemforge compose`)" % (path, md.name))


def _cmd_compose(a):
    """Write new Keys and Synth parts from the idea. Drums/Bass/Percussion stay as transcribed (re-swung)."""
    from . import compose
    bp = blueprint.load(a.blueprint)
    ip = a.idea or _idea_path(a.blueprint)
    if not Path(ip).exists():
        print("No idea file at %s. Run `stemforge idea %s` first." % (ip, a.blueprint))
        return 2
    i = json.loads(Path(ip).read_text())
    g = compose.compose(bp, i, seed=a.seed, swing_pct=a.swing, intro_bed=not a.no_intro_bed)
    out = a.out or a.blueprint[:-len(".blueprint.json")] + ".generated.blueprint.json"
    blueprint.save(g, out)
    for name, r in compose.report(g, i).items():
        print("%-8s %4d notes in %2d clips | %.1f notes/bar | velocity %d-%d (spread %.1f, %d distinct) | pitches %d-%d | "
              "outside palette: %d | off-grid (swing/micro-timing) %.0f%%" % (
                  name, r["notes"], r["clips"], r["notes_per_bar"], *r["velocity_min_max"], r["velocity_std"],
                  r["distinct_velocities"], *r["pitch_range"], r["outside_palette"], r["off_grid_pct"]))
    print("saved -> %s\nlisten: `stemforge build \"%s\" --backend midi` writes .mid files; --seed N gives a different take" % (out, out))


def _cmd_rebuild(a):
    """Rebuild Bass, Keys and Synth hit by hit from their own audio (no randomness). Drums/Percussion stay transcribed."""
    from . import idea as idea_mod, resynth
    bp = blueprint.load(a.blueprint)
    ip = a.idea or _idea_path(a.blueprint)
    if Path(ip).exists():
        i = json.loads(Path(ip).read_text())
    else:
        print("reading the song's idea first (swing, groove positions)...")
        i = idea_mod.extract(bp)
        Path(ip).write_text(json.dumps(i, indent=1))
    cache = ip[:-len(".idea.json")] + ".events.json" if ip.endswith(".idea.json") else ip + ".events.json"
    octaves = {"bass": a.octave_bass, "keys": a.octave_keys, "synth": a.octave_synth}
    gen = resynth.rebuild(bp, i, log=print, straight=a.straight, octaves=octaves, cache_path=cache)
    out = a.out or a.blueprint[:-len(".blueprint.json")] + ".rebuilt.blueprint.json"
    blueprint.save(gen, out)
    chk = resynth.check_against_audio(bp, gen)
    for name, r in gen["generation"]["report"].items():
        c = chk.get(name, {})
        print("%-8s from %-12s %4d notes | matches the stem's hits: F1 %.2f (found %.0f%%, false %.0f%%)" % (
            name, r["from"], r["notes"], c.get("hit_match", 0), 100 * c.get("found", 0), 100 * c.get("false", 0)))
    print("saved -> %s\nlisten: `stemforge build \"%s\" --backend midi` (or --backend live)" % (out, out))


def _cmd_create(a):
    """Create a song skeleton from zero in a style: deterministic, patterns from the library with their sources."""
    from .styles import create as C
    bp = C.create(a.style, a.key, a.bpm, take=a.take, short=a.short)
    g = bp["generation"]
    out_dir = Path(a.out or "created")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "%s-%s-%d.created.blueprint.json" % (a.style, g["tonic"], round(g["bpm"]))
    path = out_dir / name
    blueprint.save(bp, str(path))
    print("%s | %.0f BPM | %d bars | swing %.0f%% | take %d" % (bp["song"]["name"], g["bpm"], bp["global"]["n_bars"], g["swing_pct"], a.take))
    for line in C.describe(bp):
        print("  " + line)
    print("  checks:", {k: v for k, v in g["checks"].items() if k.startswith("bass_on")})
    for w in bp["warnings"]:
        print("  WARNING:", w)
    print("saved -> %s\nnext: `stemforge build \"%s\" --backend midi --out \"%s\"` (or --backend live)" % (path, path, out_dir))


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
    ide = sp.add_parser("idea", help="read the key colour, swing, structure and layer rhythms of an analysed song")
    ide.add_argument("blueprint"); ide.add_argument("--out"); ide.set_defaults(fn=_cmd_idea)
    cr = sp.add_parser("create", help="create a song skeleton from zero in a style (techno, house, downtempo, electro_cumbia)")
    cr.add_argument("--style", required=True, choices=["techno", "house", "downtempo", "electro_cumbia"])
    cr.add_argument("--key", help="tonic, e.g. D, F#, A (default: the style's)"); cr.add_argument("--bpm", type=float)
    cr.add_argument("--take", type=int, default=0, help="rotate through the library's alternatives (deterministic)")
    cr.add_argument("--short", action="store_true", help="cap every section at 16 bars")
    cr.add_argument("--out", help="folder for the blueprint (default ./created)")
    cr.set_defaults(fn=_cmd_create)
    rb = sp.add_parser("rebuild", help="rebuild Bass/Keys/Synth hit by hit from their audio (deterministic, no generation)")
    rb.add_argument("blueprint"); rb.add_argument("--idea"); rb.add_argument("--out")
    rb.add_argument("--straight", action="store_true", help="straight 16ths instead of the song's measured swing")
    for nm in ("bass", "keys", "synth"):
        rb.add_argument("--octave-" + nm, type=int, default=0, help="shift the %s layer by whole octaves (default 0 = as in the song)" % nm)
    rb.set_defaults(fn=_cmd_rebuild)
    co = sp.add_parser("compose", help="OLDER, experimental: writes new notes; scored far worse than `rebuild` against the stems")
    co.add_argument("blueprint"); co.add_argument("--idea"); co.add_argument("--out")
    co.add_argument("--seed", type=int, default=0, help="a different take with the same rules")
    co.add_argument("--swing", type=float, help="override the measured swing %% (50 = straight)")
    co.add_argument("--no-intro-bed", action="store_true", help="no fading D+A bed in the last 4 bars of the intro")
    co.set_defaults(fn=_cmd_compose)
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
