# Handover prompt for Claude Code (run on the Mac)

Paste everything below the line into Claude Code, started inside a clone of this repo.

---

You are continuing **stemforge** (this repo): stems of one song -> `song.blueprint.json` -> MIDI tracks/clips/scenes
in **Ableton Live 12.2.1**. Read `README.md` first. The code was written and unit-tested in a cloud container with
synthetic audio only; **none of it has run on real stems, with basic-pitch, or against a real Live set.** Treat
every "works" in the README as unproven until you run it here.

## Who I am and what I want
I make dark/hypnotic/melodic techno, dub, acid and electro cumbia on macOS (Apple Silicon), Live 12.2.1, Python 3.
I generate songs with Suno Pro and keep the stems. I want each song rebuilt in Live as a **faithful transcription**
of the real audio, not a new song in its style. I assign my own sounds afterwards (Serum 2, Pigments, Diva,
hardware), so you produce MIDI, clips, scenes and track names only. Never try to load or tweak those VSTs.

## Hard rules
1. Never invent notes, no genre templates, no random generators. If transcription is uncertain, leave the part
   out and report it.
2. Never delete or overwrite my existing tracks/clips. Work only on tracks and scenes the run created.
3. Do not say anything works until it ran against a real Live 12 session and notes were read back and compared.
4. You cannot hear audio. Say so, and tell me what to listen for.
5. Ask me before big decisions, with at most 2 options and a recommendation.
6. Stop after each phase and show me the result before starting the next.
7. Verify Live API facts against the official Live 12 Live Object Model docs, not memory.

## Phase 0: discovery (do this first)
- `stemforge discover <my stems folder>` and check the role guess for every file. Fix `stemforge/discover.py` if a
  name is misclassified.
- Create a venv, install the project, then `pip install basic-pitch`. Report which backend basic-pitch uses on this
  machine (CoreML / ONNX / TensorFlow-Metal) and run it on one short stem to prove it works. If TensorFlow is the
  problem on this Python version, propose the smallest fix (a different Python, or the ONNX/CoreML build).
- Confirm ffmpeg is installed (mp3 stems).
- Check against the official Live 12 LOM docs what exists in **12.2.1** for: `Song.create_midi_track`,
  `Song.create_scene`, `Scene.name`, `ClipSlot.create_clip`, `Clip.add_new_notes`, `Clip.remove_notes_extended`,
  `Track.create_midi_clip`, `Track.duplicate_clip_to_arrangement`, `Track.create_audio_clip`,
  `ClipSlot.create_audio_clip`. I am not sure which of the arrangement/audio calls exist in 12.2.1. Tell me exactly
  what is missing and the fallback.
- Read `AbletonMCP_Remote_Script` (my other repo, `Tavinsky1/abletonai`, `AbletonMCP_Remote_Script/__init__.py`) and
  list its real commands. Known gaps: no list-commands probe, no clear-notes, no arrangement clips, no audio import.
  Known risk: `_add_notes_to_clip` falls back to `clip.set_notes()` on Live 11, which **replaces** all notes; on Live
  12 it uses `add_new_notes`, which appends. Confirm chunked adds append in 12.2.1.
- Recommend a route into Live (my recommendation: extend the existing Remote Script, keep `.mid` export as the
  fallback). Ask me to confirm before you change anything.

## Phase 1: analyzer on one real song
Run `stemforge analyze` then `stemforge verify` on the stems I give you. Then report, honestly:
- tempo, drift, downbeat method and confidence, key and confidence;
- the sections with their evidence, and whether they look right to you from the numbers;
- per-stem note counts, confidence distribution, and the verify report.
Improve the weak spots you find (tempo/downbeat on real tracks, section labels, drum classifier thresholds in
`analyze/drums.py`, bass octave) but keep every change measurable with `verify`. Add tests for each fix.

## Phase 2: builder
- Add `list_commands` and `create_arrangement_clip` (start_time in beats, length, name, notes) to the Remote Script,
  using only calls you verified in Phase 0 (fallback: build in Session then `duplicate_clip_to_arrangement`).
  Reinstall the Remote Script and restart Live as needed.
- `stemforge build ... --backend dry` first and show me the output. Then `--backend midi` so I have drag-in files.
- Optional: original stems as audio tracks for A/B, only if 12.2.1 allows it.

## Phase 3: real test
With my open Live 12 set: build **Session** and **Arrangement** from the blueprint, read the clip notes back from
Live (`--readback`, extend it to arrangement clips), and report: what matched, what is uncertain, what I should
check by ear.

## Repo map
- `stemforge/discover.py` stem role detection. `stemforge/blueprint.py` schema + validation.
- `stemforge/analyze/` grid, key, sections, pitched, drums, quantize, clips, pipeline.
- `stemforge/verify.py` objective checks. `stemforge/build/` plan + backends (dry / midi / live).
- `tests/` synthetic-song tests and a fake-Remote-Script test (not a substitute for real Live).
