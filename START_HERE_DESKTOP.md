# Start here: Claude Code Desktop on your Mac

## 1. Set up (about 5 minutes)
```bash
git clone https://github.com/Tavinsky1/stemforge ~/Documents/stemforge
cd ~/Documents/stemforge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pytest -q        # all tests should pass
brew install ffmpeg                         # if missing
```
Also clone the Live side if you don't have it on this Mac: `Tavinsky1/abletonai` (you likely already do, as `ABLETON-AI`).

## 2. Open it in Claude Code Desktop
- Choose **Open folder** -> `~/Documents/stemforge`. Claude Code reads `CLAUDE.md` automatically, so the rules are loaded.
- If it asks to access the stems folder or the Ableton Remote Script folder, allow those two paths only.
- Put one song's stems in a folder, for example `~/Music/stems/SongName/` (WAV or MP3, one file per stem).

## 3. Before you start the session
- Open Ableton Live 12 with a **scratch set** (not your YUYO ROJO live set) and select **AbletonMCP** as a Control Surface
  in Preferences. stemforge only adds new tracks, but test on a scratch set first.
- The Remote Script listens on TCP port 9877.

## 4. First message to paste
> Read CLAUDE.md, README.md and HANDOVER_CLAUDE_CODE.md. Then do **Phase 0 only**. My stems are in
> `~/Music/stems/SongName/`. Run `stemforge discover`, check the stem roles, install `basic-pitch` and tell me which
> backend it uses on this Mac, and check ffmpeg. Then verify against the official Live 12 Live Object Model docs what
> exists in 12.2.1 for creating MIDI tracks/clips, `Clip.add_new_notes`, `Clip.remove_notes_extended`,
> `Track.create_midi_clip`, `Track.duplicate_clip_to_arrangement` and `create_audio_clip`. Read the Remote Script in
> `Tavinsky1/abletonai` and list its real commands. Recommend one route into Live with reasons, and stop for my answer.
> Do not start Phase 1 yet.

After Phase 0, continue one phase at a time: *"Go to Phase 1"*, then *"Go to Phase 2"*, then *"Go to Phase 3"*.

## 5. What you should expect
- Phase 1 gives a blueprint file plus a verify report. Expect clean bass and drums, rougher chords. It tells you what to listen for.
- Phase 3 builds Session and Arrangement in your scratch set and reads the notes back from Live. A result only counts if the read-back matches.
- If anything fails, the fallback is always `stemforge build ... --backend midi`, which writes `.mid` files per section to drag into Live.
