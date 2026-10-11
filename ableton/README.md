# Ableton side

`Stemforge/__init__.py` is Stemforge's **own** Control Surface script (TCP 9878). It is not AbletonMCP and never touches
that folder or any other script.

- Install from the app (**Install Stemforge's Ableton script...**) or copy this folder into
  `<your Ableton User Library>/Remote Scripts/` (Live > Preferences > Library shows where that is; default
  `~/Music/Ableton/User Library`). Live 12.2.1 did not list a script placed only in `~/Library/Preferences/Ableton/Live <version>/User Remote Scripts/` on the owner's Mac.
- In Live: Preferences > Link, Tempo & MIDI, choose `Stemforge` in an empty Control Surface slot (Input/Output: None).
  Live runs up to six control surfaces at once, so your other slots stay as they are.
- It can create tracks, scenes, clips and notes and read them back. It has no delete, no device loading, no mixer or transport
  commands, writes only to tracks/scenes it created itself, and never overwrites a clip.
