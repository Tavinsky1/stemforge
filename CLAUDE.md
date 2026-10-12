# CLAUDE.md: stemforge

Claude Code reads this file automatically. Full detail is in `README.md` and `HANDOVER_CLAUDE_CODE.md`.

## Project
Stems of one song -> `song.blueprint.json` -> MIDI tracks/clips/scenes in **Ableton Live 12.2.1** (Session or
Arrangement). A faithful transcription of the real audio, not a new song in its style.
Owner: Tavo (techno, dub, acid, electro cumbia; macOS Apple Silicon). Songs come from Suno Pro; stems are local.
The owner assigns their own sounds afterwards. Produce MIDI, clips, scenes and track names only. Never load or
tweak Serum 2, Pigments, Diva or any other VST.

## Hard rules
1. Transcription never invents notes: uncertain parts are left out and reported. `stemforge compose` is a SEPARATE, opt-in
   mode (owner's decision 2026-10-12) that writes new Keys/Synth parts from the song's measured idea; every generated
   note carries `source: "generated"` and its stem is named `G ...`. No genre templates: it uses only what the audio shows.
2. Never delete or overwrite the owner's existing tracks, clips or scenes. Only touch what a run created.
3. Do not say something works until it ran against a real Live 12 session and the notes were read back.
4. You cannot hear audio. Say so, and say what to listen for.
5. Ask before big decisions: at most 2 options plus a recommendation.
6. Work in phases (0 discovery, 1 analyzer, 2 builder, 3 real test). Stop after each and show the result.
7. Check Live API facts in the official Live 12 Live Object Model docs, not from memory.

## State of the code
Written in a cloud container and tested on synthetic stems, the real Low Pressure stems (offline), and fakes of Live. **Unproven against real
Live.** Stemforge talks to its OWN Ableton script (`ableton/Stemforge/`, port 9878).

## Phase 0 findings (done on the owner's Mac, 2026-10-10)
- Use **Python 3.11** (`pip install -e ".[dev,pitched]"`). basic-pitch does not install on 3.14. Backend there is CoreML.
- Live 12.2.1 has `add_new_notes` (appends, wants `MidiNoteSpecification`), `remove_notes_extended`,
  `ClipSlot.create_clip`, `Track.create_midi_clip` (docstring present; owning class still to confirm by calling it).
  `duplicate_clip_to_arrangement` is unconfirmed.
- The owner's AbletonMCP script (a different tool) builds `Live.Clip.MidiNote(...)` for `add_new_notes`; in 12.2.1 that raises and
  falls back to the deprecated replace-all `set_notes`. Stemforge's own script uses `MidiNoteSpecification` and has no fallback.
- Commands time out after 10 s: chunk big note batches.
- Two stems map to role `drums` (Drums, Percussion): keep them as separate tracks, never merge their notes.

## Compose rules (stemforge/compose.py, `RULES`)
Sources: owner's NotebookLM base (`ABLETON-AI/knowledge/HYPNOTIC_TECHNO_NOTEBOOKLM_KNOWLEDGE_BASE.md`, `knowledge/research/
arrangement_conventions.md`, `knowledge/arrangement/arrangement_rules.json`) plus web research on techno structure, dub chords,
polymeter and swing. Rules are about structure and dynamics and are checked by `compose.report`; taste is judged by ears.
Do not add notes that the audio does not support; the key is read from audio chroma (overtone-aware), not from the analyzer's
major/minor guess (Low Pressure: D drone, open fifth, Eb colour, ~60% swing, NOT G minor).

## Desktop app
`stemforge/app/` is a native PySide6 window (Stems -> Analyze -> Send to Ableton). Selection of stems, build and read-back
live in `stemforge/workflow.py`, shared by the CLI and the app. The app never contacts Live until the user clicks
"Connect to Ableton" (read-only probe, 10 s poll afterwards, paused during a build). Tested offscreen only (`tests/test_app.py`);
never run against real Live. `packaging/build_app.sh` builds `dist/Stemforge.app` (PyInstaller; `--selftest` runs pyin + Basic
Pitch inside the bundle).

## Ableton side: Stemforge's OWN script, separate from the owner's AbletonMCP
- `ableton/Stemforge/__init__.py`: its own Control Surface, port 9878. The installer writes only
  `<configured User Library>/Remote Scripts/Stemforge/__init__.py` (from Live's `Library.cfg`; fallback
  `Preferences/.../User Remote Scripts/Stemforge/`) and refuses any other path; it never reads, backs up, renames or deletes
  `AbletonMCP` or any other script folder (tests prove it). Every real install is logged in `INSTALL_LOG.md` with its revert.
- The owner's Live keeps its User Library outside `~/Music` (`~/Documents/ableton projects/SharedAbleton`); a script in the
  Preferences folder was NOT listed there. Two different AbletonMCP copies exist (Preferences, User Library): never touch either.
- `claim_scene` (script-2) lets a build start at scene 1 by taking over leading scene rows that are completely empty
  (no clip, no name, no tempo override); a non-empty row ends reuse and is never touched.
- The script cannot delete, load devices or change the mixer/transport. It writes only to tracks and scenes it created in
  the current Live session, and never overwrites a clip. Ownership uses Live's object identity (`_live_ptr`/`==`); if that
  does not hold in real Live it fails CLOSED (refuses writes), which the smoke test will show.
- The smoke test creates a track and a scene named `stemforge_smoke`; the script can't delete them, so the owner removes them.
- Never contact port 9878 or 9877 without the owner's "scratch open, go".

## Commands
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest -q
stemforge discover <stems>   # then analyze / verify / clips / build (see README)
```

## Layout
`stemforge/analyze/` (grid, key, sections, pitched, drums, quantize, clips, pipeline), `stemforge/verify.py`,
`stemforge/build/` (plan + backends dry/midi/live), `tests/`. The blueprint JSON (schema_version 1) is the only
contract between analyzer and builder.

## Related repo
The owner's other tool, AbletonMCP (`Tavinsky1/abletonai`, TCP 9877), is NOT part of Stemforge and must not be modified or
replaced by it. Stemforge no longer depends on it.