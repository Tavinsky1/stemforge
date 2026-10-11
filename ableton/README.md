# Ableton side

`AbletonMCP/__init__.py` is the Remote Script that runs inside Ableton Live (TCP port 9877). It is a copy of
`AbletonMCP_Remote_Script/__init__.py` from the owner's ABLETON-AI repo (commit 9e5c9df, version `stemforge-2`),
versioned here so the app and the script change together. The app's "Install / update Remote Script" button copies it
into Live's `User Remote Scripts` folder after backing up whatever is there to `~/Documents/ableton-backups/`.

After installing: in Live, Preferences > Link, Tempo & MIDI, set a Control Surface slot to `AbletonMCP` (toggle it off and
on to reload; restart Live if the version shown in Stemforge's status pill is still old).
