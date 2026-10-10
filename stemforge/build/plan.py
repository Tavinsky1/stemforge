"""Turn a blueprint into an ordered list of builder actions (backend-independent)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..analyze.grid import BEATS_PER_BAR


@dataclass
class Plan:
    mode: str                      # "session" | "arrangement"
    tempo: float
    tracks: list[str]              # stem names, in order
    scenes: list[str]              # section names (session mode scenes; also used as arrangement locators)
    # (stem, section_index, clip_id, start_beat, length_beats, name)
    placements: list[tuple] = field(default_factory=list)
    clips: dict = field(default_factory=dict)


def make_plan(bp: dict, mode: str = "session", only_stems: list[str] | None = None) -> Plan:
    if mode not in ("session", "arrangement"):
        raise ValueError("mode must be 'session' or 'arrangement'")
    clips = {c["id"]: c for c in bp["clips"]}
    used = []
    for p in bp["placements"]:
        if (only_stems is None or p["stem"] in only_stems) and p["stem"] not in used:
            used.append(p["stem"])
    order = [s["name"] for s in bp["stems"] if s["name"] in used]
    plan = Plan(mode=mode, tempo=bp["global"]["tempo"], tracks=order,
                scenes=[s["name"] for s in bp["sections"]], clips=clips)
    secs = {s["index"]: s for s in bp["sections"]}
    for p in bp["placements"]:
        if p["stem"] not in order:
            continue
        sec = secs[p["section"]]
        c = clips[p["clip"]]
        plan.placements.append((p["stem"], sec["index"], c["id"], sec["start_bar"] * BEATS_PER_BAR,
                                c["length_beats"], "%s %s" % (p["stem"], sec["label"])))
    return plan
