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
| Live build via Stemforge's own Ableton script (separate Control Surface, port 9878) | Written; tested against stand-ins for Live's objects and a fake socket peer. **Not tested against real Live 12.** |
| Live Arrangement build | Implemented in the script (`Track.create_midi_clip` + chunked notes); **not yet run in real Live**. |
| Audio A/B tracks (original stems as audio) | Not implemented. Depends on what Live 12.2.1's API allows. |

## Desktop app (native window, not a browser)

```bash
pip install -e ".[app,pitched]"     # Python 3.11
stemforge-app                       # or double-click Stemforge.command on macOS
```

1. **Stems:** drop the folder (or click). Each stem is labelled automatically; fix any label with the dropdown, untick what you don't want.
2. **Analyze:** tempo, key, a colour timeline of the sections (hover a section to see why it was placed), and a Good / Check by ear / Left out verdict per stem.
3. **Send to Ableton:** Session (one scene per section) or Arrangement. *Preview* changes nothing, *Export .mid* needs no Live,
   *Build in Ableton* adds new tracks and scenes, then reads the notes back from Live and reports how many clips match.

The button at the top (**Connect to Ableton**) checks whether Ableton is reachable (port 9878), shows the Stemforge script version, and
whether Arrangement mode is available. Nothing contacts Live until you press it. Live's tempo is left alone unless you tick the box. Screenshot (synthetic demo song): `docs/app-screenshot.png`.

Status: the window is tested headless (offscreen) against the same library calls as the CLI. It has **not** been run against real
Live, and the `.app` bundle is not built yet (use `Stemforge.command` for now).

## Idea and compose (when transcription is not enough)
Dense polyphonic synths transcribe badly (about 40% recall). So there is a second route:

```bash
stemforge idea    "<song>.blueprint.json"            # key colour, swing, structure, where each layer really hits -> .idea.json/.md
stemforge compose "<song>.blueprint.json" --seed 0   # new Keys + Synth from that idea -> .generated.blueprint.json
stemforge build   "<song>.generated.blueprint.json" --backend midi    # or --backend live
```
Drums, Bass and Percussion stay as transcribed (16ths re-swung to the measured groove). Keys and Synth are written from
the measured rhythm, dynamics, drone/fifth/colour tones and bass roots, with velocity accents, swing, micro-timing, an
interlocking rhythm and a 5/7-note pitch cell that phases against the 16-step grid. Edit `.idea.json` to correct a reading,
and use `--seed` for another take. `compose.report` checks the rules (palette, register, velocity spread); ears decide taste.

## Ableton setup (separate from your other scripts)

Stemforge ships its **own** Control Surface script, `Stemforge`, in `ableton/Stemforge/`. It runs next to anything else you use
(for example AbletonMCP) and never touches those folders. Live supports up to six control surfaces at once
([Live 12 manual](https://www.ableton.com/live-manual/12/midi-and-key-remote-control/)).

1. In the app press **Install Stemforge's Ableton script…** and confirm. It creates exactly one file,
   `Stemforge/__init__.py` inside the `Remote Scripts` folder of **the User Library your Live is configured with** (read from
   Live's `Library.cfg`, e.g. `<your library>/User Library/Remote Scripts/`; only if none is configured it uses
   `~/Library/Preferences/Ableton/Live <version>/User Remote Scripts/`). An existing, different Stemforge script is backed up
   first to `~/Documents/ableton-backups/`. Nothing else is read, changed or deleted. `INSTALL_LOG.md` records every write
   with its revert command.
2. In Live: **Preferences > Link, Tempo & MIDI**. In an *empty* Control Surface slot choose **Stemforge** (Input and Output: None).
   Leave your other slots alone. Restart Live if Stemforge is not in the list.
3. In the app press **Connect to Ableton**.

The script can only *create* (tracks, scenes, clips, notes) and read. It has no delete, no device loading and no mixer/transport
commands, and it refuses to write to any track or scene it did not create itself.

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
stemforge build song.blueprint.json --backend live --mode session --readback # needs Live 12 + Stemforge's script selected as a Control Surface
stemforge build song.blueprint.json --backend live --mode arrangement        # same, needs the script's arrangement commands
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
