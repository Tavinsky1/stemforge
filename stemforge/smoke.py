"""Live smoke test: prove the Remote Script writes and reads back notes correctly.

Run this on a SCRATCH Live set before any real build. It creates one new MIDI
track ("stemforge_smoke") and only ever writes into clips on that track, so
no existing track, clip or scene is touched. The notes are a fixed diagnostic
pattern, not music; nothing here is transcribed from a stem.

Checks, in order (stops at the first failure):
  1. list_commands: the loaded Remote Script is the new one (reports version,
     source hash and file path so you can see which copy Live loaded).
  2. Session clip: create_clip, then two add_notes_to_clip chunks, read back
     with get_clip_notes. Counts must add up and every note must match.
     (This is what proves chunked adds APPEND rather than replace.)
  3. Arrangement clip: create_arrangement_clip with the same notes; Live's own
     read-back count must equal the number sent.
"""
from __future__ import annotations

from .build.backends import LiveBackend, NotSupported, compare_notes

SMOKE_TRACK = "stemforge_smoke"
REQUIRED = {"list_commands", "create_midi_track", "set_track_name", "create_clip",
            "add_notes_to_clip", "get_clip_notes", "create_arrangement_clip"}


def _fixture() -> tuple[list[dict], list[dict]]:
    """Two chunks of 6 notes; distinct pitch and time so a replace would show."""
    def note(i):
        return {"pitch": 60 + i, "start": i * 0.5, "duration": 0.25, "velocity": 100}
    return [note(i) for i in range(6)], [note(i) for i in range(6, 12)]


def _to_cmd(notes):
    return [{"pitch": n["pitch"], "start_time": n["start"], "duration": n["duration"],
             "velocity": n["velocity"], "mute": False} for n in notes]


def run(host="127.0.0.1", port=9877, cleanup=False, log=print) -> dict:
    live = LiveBackend(host=host, port=port, log=log)
    report = {"ok": False, "steps": []}

    def step(name, ok, **detail):
        report["steps"].append({"step": name, "ok": ok, **detail})
        log("[%s] %s %s" % ("PASS" if ok else "FAIL", name, detail if detail else ""))
        return ok

    # 1. which Remote Script is loaded?
    try:
        info = live.send("list_commands")
    except NotSupported:
        step("list_commands", False, why="loaded Remote Script is the OLD copy (no list_commands). "
             "Install the updated one and reload it in Live.")
        return report
    missing = sorted(REQUIRED - set(info.get("commands", [])))
    if not step("list_commands", not missing, version=info.get("version"),
                sha256=(info.get("source_sha256") or "")[:12], file=info.get("file"), missing=missing):
        return report

    sess = live.send("get_session_info")
    log("set has %s tracks, %s scenes" % (sess.get("track_count"), sess.get("scene_count")))

    first, second = _fixture()
    allnotes = first + second

    # 2. session clip, chunked adds, read back
    r = live.send("create_midi_track", {"index": -1})
    track = r["index"]
    live.created_tracks.append(track)
    live.send("set_track_name", {"track_index": track, "name": SMOKE_TRACK})
    live._guard(track)
    live.send("create_clip", {"track_index": track, "clip_index": 0, "length": 8.0})
    live.send("add_notes_to_clip", {"track_index": track, "clip_index": 0, "notes": _to_cmd(first)})
    after_one = live.read_back(track, 0)
    live.send("add_notes_to_clip", {"track_index": track, "clip_index": 0, "notes": _to_cmd(second)})
    got = live.read_back(track, 0)
    cmp = compare_notes(allnotes, got)
    appended = len(after_one) == len(first) and len(got) == len(allnotes)
    if not step("session chunked append", appended and cmp["match"],
                after_chunk1=len(after_one), after_chunk2=len(got), expected=len(allnotes),
                missing=cmp["missing"][:3], extra=cmp["extra"][:3]):
        return _finish(live, track, cleanup, report, log)

    # 3. arrangement clip, Live's own read-back count
    try:
        a = live.send("create_arrangement_clip", {"track_index": track, "start_time": 0.0,
                                                  "length": 8.0, "name": "smoke arr",
                                                  "notes": _to_cmd(allnotes)})
        step("arrangement clip", a.get("notes_readback") == len(allnotes),
             sent=a.get("notes_sent"), readback=a.get("notes_readback"),
             start=a.get("start_time"), end=a.get("end_time"))
    except Exception as exc:   # report, don't hide
        step("arrangement clip", False, error=str(exc))

    return _finish(live, track, cleanup, report, log)


def _finish(live, track, cleanup, report, log):
    report["ok"] = all(s["ok"] for s in report["steps"])
    report["track_index"] = track
    if cleanup:
        # only ever our own track, and only if its name still matches
        info = live.send("get_track_info", {"track_index": track})
        if info.get("name") == SMOKE_TRACK and track in live.created_tracks:
            live.send("delete_track", {"track_index": track})
            log("deleted smoke track %d" % track)
        else:
            log("not deleting track %d: name is %r" % (track, info.get("name")))
    else:
        log("left track %d '%s' in the set for you to inspect; delete it by hand "
            "(or rerun with --cleanup)" % (track, SMOKE_TRACK))
    log("SMOKE TEST %s" % ("PASSED" if report["ok"] else "FAILED"))
    return report
