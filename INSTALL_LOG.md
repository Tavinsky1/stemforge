# INSTALL_LOG: everything Stemforge has written outside this repo

One entry per real change to your machine, newest last. Each entry says what was written, how it was checked,
and the exact command that undoes it. Stemforge never deletes anything itself; reverts are manual `rm` commands.

Never touched by any entry: `AbletonMCP` (either copy), `TouchDesigner`, anything under `Live 12.2.2/`.

## 2026-10-11 15:09 — script placed in Live's Preferences folder (did NOT show up in Live; superseded by the next entry)
- Wrote: `~/Library/Preferences/Ableton/Live 12.2.1/User Remote Scripts/Stemforge/__init__.py`
  (sha256 `628cb866…ac18eb6db`, stemforge-script-1). Created by `installer.install()` from the app/CLI code.
- Side effect, removed again the same hour: a `__pycache__/` that a compile check of mine created inside that folder.
- Why it failed: this Live keeps its User Library at `~/Documents/ableton projects/SharedAbleton`; it lists scripts from
  `<User Library>/Remote Scripts`, and its dropdown did not list this one.
- Still there, unused and harmless. Revert (optional):
  `rm -r "$HOME/Library/Preferences/Ableton/Live 12.2.1/User Remote Scripts/Stemforge"`

## 2026-10-11 15:23 — script placed in your User Library (the folder Live scans)
- Wrote exactly one file:
  `~/Documents/ableton projects/SharedAbleton/User Library/Remote Scripts/Stemforge/__init__.py`
  (sha256 `628cb86600c708604bea3bfa6408f355dd0f2ae46ca024b4aa6d006ac18eb6db`, stemforge-script-1, 18,214 bytes).
- Folder `Stemforge/` was created by the same step. No backup was needed (nothing was there).
- Checked: sha256 of all 43 files in the three script folders (User Library `Remote Scripts`, Preferences 12.2.1 and 12.2.2
  `User Remote Scripts`) before and after. The only difference is the one added line for this file.
  `AbletonMCP/__init__.py` in the User Library is still `ecec75ef…2c33a3a` (49,831 bytes, Jul 31).
- Code change that allowed it: `stemforge/app/installer.py` now reads the User Library from Live's `Library.cfg`
  (`_assert_safe` also accepts `Remote Scripts/Stemforge/__init__.py`; still refuses any `AbletonMCP` path). Tests: 64 pass.
- Revert (removes only Stemforge's script; Live then simply stops listing "Stemforge"):
  `rm -r "$HOME/Documents/ableton projects/SharedAbleton/User Library/Remote Scripts/Stemforge"`
- Live side (done by you in Live, not by Stemforge): Preferences > Link, Tempo & MIDI > a free Control Surface slot >
  `Stemforge`, Input/Output None. To revert, set that slot back to None.

## 2026-10-11 15:49 — Stemforge script updated to stemforge-script-2 (adds `claim_scene`)
- Why: the owner asked for the build to start at scene 1; the script could only write into scene rows it created itself,
  so the first section would have landed at scene 9. `claim_scene` hands Stemforge an EXISTING scene row, but only when
  the row is completely empty (no clip on any track, no name or just a number, no tempo/time-signature override).
  Anything else is refused and untouched. Nothing else changed (still no delete, no devices, no mixer/transport).
- Wrote (replaced our own file): `~/Documents/ableton projects/SharedAbleton/User Library/Remote Scripts/Stemforge/__init__.py`
  now sha256 `899a1af97129125b91e7cc8d551f67cca5add41b983cc64fe7f930a5374dc763` (stemforge-script-2).
- Backup of the previous file (script-1, sha `628cb866…`):
  `~/Documents/ableton-backups/Stemforge-20261011-154907/__init__.py` (new folder, created by the installer).
- Checked: before/after hashes of the three script folders differ only in that one line; AbletonMCP and TouchDesigner
  untouched. 70 tests pass.
- Revert to script-1:
  `cp "$HOME/Documents/ableton-backups/Stemforge-20261011-154907/__init__.py" "$HOME/Documents/ableton projects/SharedAbleton/User Library/Remote Scripts/Stemforge/__init__.py"`
  (then restart Live). The app/CLI then warn that the first section goes after the existing scenes.
- Live loads scripts at launch: restart Live for v2 to take effect (the running Live still holds v1).

## 2026-10-11 15:55 — Session build of "Low Pressure" into the open scratch Live set (changes the SET, not files on disk)
- Command: `stemforge build "Low Pressure Stems (126BPM).blueprint.json" --mode session --backend live --readback`
  via Stemforge's script-2 on port 9878. Set tempo left at 147 (song is 126.01). Port 9877 / AbletonMCP not used.
- Added 5 MIDI tracks after your 2: `0 Drums`, `1 Bass`, `3 Keyboard`, `4 Percussion`, `5 Synth` (track indexes 3–7 in Live).
- Scenes: rows 1–8 (your empty, unnamed scenes) were claimed and renamed to the first 8 sections; rows 9–13 are new.
  62 clips, 7,053 notes. Left out: `2 Guitar` (no notes), `6 Other` (coverage 1%), `7 Brass` (onset precision 0.01).
- Verified twice: the CLI read-back (62/62) and a separate read-back of every clip (62/62 exact, 7,053 notes).
- Revert (by hand in Live, Stemforge's script cannot delete): delete the 5 tracks above, delete scenes 9–13, and clear the
  names of scenes 1–8 (they were unnamed before). Or close the set without saving.

## 2026-10-12 20:23 — Stemforge.app placed on the Desktop
- Created: `~/Desktop/Stemforge.app` (copy of `stemforge/dist/Stemforge.app`, arm64, ad-hoc signed, own icon,
  contains script-2 and Idea & Compose). Removed my earlier `~/Desktop/Stemforge.command` (it only launched the dev copy).
- The app never contacts Ableton until you press "Connect to Ableton".
- Revert: `rm -r ~/Desktop/Stemforge.app`. To update after code changes: rebuild with `bash packaging/build_app.sh`
  and copy again: `rm -r ~/Desktop/Stemforge.app && ditto dist/Stemforge.app ~/Desktop/Stemforge.app`.

## 2026-10-12 21:xx — Desktop app replaced with the clean-rebuild version (see commit)
- `~/Desktop/Stemforge.app` replaced by a rebuild of `dist/Stemforge.app` (same location, same icon). Step 3 of the window is
  now "Clean rebuild" (Bass, Keys, Synth from the audio); the random "compose" card is gone from the app.
- Revert: `rm -r ~/Desktop/Stemforge.app` (the previous version is in git history; rebuild with `packaging/build_app.sh`).

## Not done yet (waiting for "scratch open, go")
- No command has been sent to Live (ports 9877 and 9878). The smoke test will create one track and one scene named
  `stemforge_smoke`; delete them by hand afterwards (Stemforge's script cannot delete).
