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
- If it asks for access, allow the stems folder and (only when you press the install button) Ableton's preferences folder.
- Put one song's stems in a folder, for example `~/Music/stems/SongName/` (WAV or MP3, one file per stem).

## 3. Before you start the session
- Open Ableton Live 12 with a **scratch set** (not your YUYO ROJO live set) and select **Stemforge** as a Control Surface (an empty slot; leave your other slots as they are)
  in Preferences. stemforge only adds new tracks, but test on a scratch set first.
- Stemforge's script listens on TCP port 9878 (your AbletonMCP, if you use it, stays on 9877 and is never touched).
  Install it from the app's **Install Stemforge's Ableton script…** button; see README.md > Ableton setup.

## 4. What to do first
Phase 0 (discovery) is finished; its findings are in `CLAUDE.md`. Open the window (`stemforge-app`, `Stemforge.command` or
`dist/Stemforge.app`), drop a stems folder and press **Analyze song**. Nothing contacts Ableton until you press
**Connect to Ableton**, and you only do that once a scratch set is open and Stemforge's script is selected in Live.

## 5. What you should expect
- Phase 1 gives a blueprint file plus a verify report. Expect clean bass and drums, rougher chords. It tells you what to listen for.
- Phase 3 builds Session and Arrangement in your scratch set and reads the notes back from Live. A result only counts if the read-back matches.
- If anything fails, the fallback is always `stemforge build ... --backend midi`, which writes `.mid` files per section to drag into Live.
