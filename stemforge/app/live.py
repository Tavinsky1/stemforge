"""Quick, side-effect-free probe of the Ableton connection for the status pill."""
from __future__ import annotations

from ..build.backends import LiveBackend

ARRANGEMENT_COMMANDS = {"create_arrangement_clip", "add_notes_to_arrangement_clip", "get_arrangement_clip_notes"}


def probe(port: int = 9877, timeout: float = 0.8, known: dict | None = None) -> dict:
    """Returns {connected, tracks, scenes, tempo, version, arrangement, message}. Never raises, never changes the set.

    `known` is a previous connected result: its script version / arrangement support are reused so a poll costs
    a single read-only command (get_session_info) instead of two."""
    b = LiveBackend(port=port, timeout=timeout, log=lambda *_: None)
    try:
        info = b.send("get_session_info")
    except (OSError, TimeoutError):
        return {"connected": False, "arrangement": False,
                "message": "Ableton not found. Open Live 12 and select AbletonMCP as a Control Surface."}
    except Exception as e:  # listening but misbehaving
        return {"connected": False, "arrangement": False, "message": "Ableton answered with an error: %s" % e}
    out = {"connected": True, "tracks": info.get("track_count"), "scenes": info.get("scene_count"),
           "tempo": info.get("tempo"), "version": None, "arrangement": False}
    try:
        if known and known.get("connected"):
            out["version"], out["arrangement"] = known.get("version"), known.get("arrangement", False)
        else:
            r = b.send("list_commands")
            out["version"] = r.get("version")
            out["arrangement"] = ARRANGEMENT_COMMANDS <= set(r.get("commands", []))
    except Exception:
        pass   # older Remote Script without list_commands: Session mode still works
    finally:
        try:
            b.sock.close()
        except Exception:
            pass
    bits = ["Ableton connected"]
    if out["tracks"] is not None:
        bits.append("%s tracks" % out["tracks"])
    if out["tempo"]:
        bits.append("%.1f BPM" % float(out["tempo"]))
    if out["version"] is None:
        bits.append("old Remote Script (Session mode only)")
    elif not out["arrangement"]:
        bits.append("Arrangement needs a script update")
    out["message"] = " · ".join(bits)
    return out
