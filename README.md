# stemforge

Reads **all stems of one song together**, transcribes them to MIDI, and rebuilds the song in
**Ableton Live 12** as MIDI tracks, clips and scenes (Session or Arrangement). It is a
transcription tool: it never invents notes, uses no genre templates and no random generators.
If a part cannot be transcribed it is left out and reported.

You add your own instruments afterwards. stemforge only makes MIDI, clips, scenes and track names.

```
stems/ ──► analyze ──► song.blueprint.json ──► build ──► Live 12  (or .mid files, or a dry run)
              │                 ▲
              └── verify ───────┘   (render MIDI to sine/click, compare with each stem)
```

Each stage runs on its own. The blueprint JSON (`schema_version` 1) is the only contract between them.

## Status (be honest about this)

| Piece | State |
|---|---|
| discover, grid/tempo, key, sections, drums, mono pitch (pyin), quantize, clips, verify, `.mid` export, dry run | Written; unit-tested **on synthetic stems only**. Never run on a real Suno song. |
| Polyphonic transcription (`basic-pitch`) | Code path written, **not tested here** (not installed in the dev container). Must be checked on Apple Silicon. Without it, poly stems are skipped and reported. |
| Live Session build via the AbletonMCP Remote Script | Written; tested only against a **fake** Remote Script. **Not tested against real Live 12.** |
| Live Arrangement build | **Not implemented in the Remote Script.** Needs a new `create_arrangement_clip` command; see `HANDOVER_CLAUDE_CODE.md`. |
| Audio A/B tracks (original stems as audio) | Not implemented. Depends on what Live 12.2.1's API allows. |

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install basic-pitch        # polyphonic stems; check which backend it reports (see below)
brew install ffmpeg            # for mp3 stems
```

## Run each phase

```bash
# Phase 0: what is in the folder, and what is installed
stemforge discover path/to/stems

# Phase 1: analyze -> path/to/stems/<name>.blueprint.json
stemforge analyze path/to/stems --skip fx
stemforge verify  path/to/stems/<name>.blueprint.json
stemforge clips   path/to/stems/<name>.blueprint.json --min-confidence 0.5   # re-cut clips with a stricter threshold

# Phase 2: build. Always dry-run first.
stemforge build song.blueprint.json --backend dry  --mode session
stemforge build song.blueprint.json --backend midi --out out/                # .mid per section + full.mid, no Live needed
stemforge build song.blueprint.json --backend live --mode session --readback # needs Live 12 + AbletonMCP running
stemforge build song.blueprint.json --backend live --mode arrangement        # needs the Remote Script extension
```

Options worth knowing: `--resolution 0.25` (16th-note grid), `--strength 1.0` (1 = snap fully, lower keeps
the human timing), `--min-confidence`.

## What the analyzer does

- **Grid:** tempo and phase from a comb filter on the onset envelope (low band weighted), local phase per song
  chunk to detect drift. A steady song gets a straight grid; a drifting one keeps its tracked beats (and warns,
  because Live then plays at one constant tempo). Assumes 4/4. The downbeat comes from low-band energy; when every
  beat looks alike (four-on-the-floor) it assumes the first strong event is bar 1 and warns.
- **Key:** Krumhansl-Schmuckler on the pitched stems, with a confidence from the margin over the runner-up.
  Modal music (dorian, phrygian) is reported as the nearest major/minor.
- **Sections:** per-bar activity of every stem; boundaries where the mix of active stems changes, snapped to
  4-bar multiples when within a bar. Each boundary lists its evidence (which stem enters or leaves, energy change).
  Labels (intro/groove/build/drop/breakdown/peak/outro) come from measured drums/bass presence, energy and slope.
- **Pitched stems:** `basic-pitch` when installed (bass and vocals use a frequency window and are made monophonic).
  Without it only monophonic stems fall back to `pyin`; polyphonic stems are skipped, not guessed.
- **Drums:** onset detection, then a simple spectral classifier (kick / snare / closed hat / open hat / perc) mapped
  to GM notes (36, 38, 42, 46, 75). Stems named kick/snare/hat skip the classifier. A weak hit right after a much
  louder one is treated as ring-out and dropped; very quiet hits are kept with half confidence.
- **Clips:** identical content across sections becomes one clip, reused. `loop_period_bars` records repeats.

## Safety

The Live backend only creates **new** tracks and scenes and refuses to touch any track or scene it did not create
in the same run. Existing clips are never modified. There is no delete anywhere in the builder.

## Limits you should know

- Tempo is constant in Live. Songs with drift will not line up with the original audio beyond a few bars.
- Dense polyphony, pads and effects-heavy stems will transcribe approximately. Check chords by ear.
- The verification report is objective only (onset overlap, pitch-class similarity, coverage). It cannot judge sound.

## Tests

```bash
pytest -q
```
