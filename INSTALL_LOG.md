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

## Not done yet (waiting for "scratch open, go")
- No command has been sent to Live (ports 9877 and 9878). The smoke test will create one track and one scene named
  `stemforge_smoke`; delete them by hand afterwards (Stemforge's script cannot delete).
