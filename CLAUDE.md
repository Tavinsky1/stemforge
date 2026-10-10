# CLAUDE.md: stemforge

Claude Code reads this file automatically. Full detail is in `README.md` and `HANDOVER_CLAUDE_CODE.md`.

## Project
Stems of one song -> `song.blueprint.json` -> MIDI tracks/clips/scenes in **Ableton Live 12.2.1** (Session or
Arrangement). A faithful transcription of the real audio, not a new song in its style.
Owner: Tavo (techno, dub, acid, electro cumbia; macOS Apple Silicon). Songs come from Suno Pro; stems are local.
The owner assigns their own sounds afterwards. Produce MIDI, clips, scenes and track names only. Never load or
tweak Serum 2, Pigments, Diva or any other VST.

## Hard rules
1. Never invent notes. No genre templates, no random generators. Uncertain parts are left out and reported.
2. Never delete or overwrite the owner's existing tracks, clips or scenes. Only touch what a run created.
3. Do not say something works until it ran against a real Live 12 session and the notes were read back.
4. You cannot hear audio. Say so, and say what to listen for.
5. Ask before big decisions: at most 2 options plus a recommendation.
6. Work in phases (0 discovery, 1 analyzer, 2 builder, 3 real test). Stop after each and show the result.
7. Check Live API facts in the official Live 12 Live Object Model docs, not from memory.

## State of the code
Written in a cloud container and tested only on synthetic stems and a fake Remote Script. **Unproven on real
stems, with basic-pitch on Apple Silicon, and against real Live.** Arrangement mode needs a new Remote Script
command that does not exist yet.

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
The Live side is the AbletonMCP Remote Script in `Tavinsky1/abletonai` (`AbletonMCP_Remote_Script/__init__.py`,
TCP 9877, JSON `{"type","params"}`). Extending it is part of Phase 2; confirm with the owner before editing it.
