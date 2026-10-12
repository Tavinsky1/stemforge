"""Assemble stemforge/styles/library/styles.json: the patterns and style definitions "create from zero" uses.

Dev tool (reads this Mac's NotebookLM exports and the measured bass cells); the app only reads the JSON.
Every pattern carries its source:
  notebooklm  patterns exported from the owner's NotebookLM research (ABLETON-AI/knowledge/research/patterns_*.json)
  measured    bar patterns measured from real loops/stems (stemforge/styles/mine.py), with the files they came from
  documented  rules published by producers/magazines, with the URL

Run:  python -m stemforge.styles.build_library
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE / "library"
KNOW = Path(__file__).resolve().parents[3] / "knowledge"          # ABLETON-AI/knowledge

NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi_of(name: str) -> int:
    """'C3' = 60 (Ableton naming), 'Eb1', 'C#1', 'A#1'."""
    m = re.fullmatch(r"([A-G])([#b]?)(-?\d)", name.strip())
    if not m:
        raise ValueError("bad note name %r" % name)
    pc = NOTE_PC[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    return 12 * (int(m.group(3)) + 2) + pc


def _notes_from_notebooklm(item: dict) -> list[dict]:
    out = []
    for n in item["notes"]:
        out.append({"start": float(n["start"]), "pitch": midi_of(n["pitch"]) if isinstance(n["pitch"], str) else int(n["pitch"]),
                    "vel": int(n.get("velocity", 90)), "dur": float(n.get("duration", 0.25))})
    return out


def load_notebooklm() -> dict[str, dict]:
    pats: dict[str, dict] = {}
    for fn in ("patterns_bass.json", "patterns_percussion.json", "patterns_percussion_gap2.json", "patterns_melodic.json",
               "patterns_melodic_gap2.json", "patterns_synth.json", "patterns_synth_gap2.json"):
        for it in json.load(open(KNOW / "research" / fn)):
            pats[it["id"]] = {
                "id": it["id"], "name": it["pattern_name"], "bars": int(it.get("bars", 1)), "notes": _notes_from_notebooklm(it),
                "purpose": it.get("musical_purpose", ""), "genre": it.get("genre", ""),
                "tempo_range": [it["tempo_range"]["min"], it["tempo_range"]["max"]],
                "source": {"kind": "notebooklm", "ref": "knowledge/research/" + fn, "genre": it.get("genre", "")},
            }
    # exports dropped into knowledge/notebooklm/ (same JSON format as the files above) are picked up too
    for extra in sorted((KNOW / "notebooklm").glob("patterns_*.json")) if (KNOW / "notebooklm").exists() else []:
        for it in json.load(open(extra)):
            pats[it["id"]] = {
                "id": it["id"], "name": it["pattern_name"], "bars": int(it.get("bars", 1)), "notes": _notes_from_notebooklm(it),
                "purpose": it.get("musical_purpose", ""), "genre": it.get("genre", ""),
                "tempo_range": [it["tempo_range"]["min"], it["tempo_range"]["max"]],
                "source": {"kind": "notebooklm", "ref": "knowledge/notebooklm/" + extra.name, "genre": it.get("genre", "")}}
    return pats


def steps(step_list, pitch: int, vel, dur: float = 0.2, bars: int = 1) -> list[dict]:
    """Notes on 16th steps. vel: int, or {step: velocity}, or a function step -> velocity."""
    out = []
    for s in step_list:
        v = vel(s) if callable(vel) else (vel[s] if isinstance(vel, dict) else vel)
        out.append({"start": s * 0.25, "pitch": pitch, "vel": int(v), "dur": dur})
    return out


ATTACK = "https://www.attackmagazine.com/technique/beat-dissected/"
DOC_SRC = {
    "techno_rolling_bass": ["https://www.attackmagazine.com/technique/tutorials/warehouse-rolling-techno-bass/",
                            "https://www.studiobrootle.com/rolling-techno-bassline-ableton/"],
    "rolling_techno_beat": [ATTACK + "rolling-techno/"],
    "house_beat": [ATTACK + "rolling-deep-house/", ATTACK + "soulful-deep-house/", "https://ampedstudio.com/blog/how-tomake-a-house-beat/"],
    "house_bass": ["https://theproducerschool.com/blogs/featured-blogs/master-modern-tech-house-bass-lines-complete-tutorial-guide"],
    "downtempo_beat": [ATTACK + "chillout-beat-raw-strip-hop/"],
    "kb": ["knowledge/HYPNOTIC_TECHNO_NOTEBOOKLM_KNOWLEDGE_BASE.md section 5 (velocity tiers, swing)"],
}


def documented() -> dict[str, dict]:
    """Patterns written down in published sources. Step numbers here are 0-based 16ths (the articles count from 1)."""
    d: dict[str, dict] = {}

    def add(pid, name, notes, purpose, src, bars=1, role=None):
        d[pid] = {"id": pid, "name": name, "bars": bars, "notes": notes, "purpose": purpose, "genre": "",
                  "tempo_range": [0, 0], "source": {"kind": "documented", "ref": src}}
    kb_tier = lambda s: 100 if s % 4 == 0 else (80 if s % 4 == 2 else 58)          # strong / medium / subtle (KB section 5)
    add("DOC-KICK-4OTF", "Four on the floor", steps([0, 4, 8, 12], 36, 104, 0.25), "kick on every quarter (positions 1,5,9,13)",
        DOC_SRC["house_beat"])
    add("DOC-TECHNO-GHOSTKICK", "Four on the floor + ghost kicks",
        steps([0, 4, 8, 12], 36, 104, 0.25) + steps([3, 11], 36, 42, 0.15),
        "ghost kick just before beats 2 and 4 'to create a pendulum effect' (Rolling Techno, 131 BPM)", DOC_SRC["rolling_techno_beat"])
    add("DOC-CLAP-24", "Clap on 2 and 4", steps([4, 12], 39, 100, 0.2), "clap/snare on beats 2 and 4", DOC_SRC["house_beat"])
    add("DOC-SNARE-24", "Snare on 2 and 4", steps([4, 12], 38, 100, 0.2), "snare on beats 2 and 4 (chillout beat)",
        DOC_SRC["downtempo_beat"])
    add("DOC-OHAT-OFFBEAT", "Open hat on the offbeats", steps([2, 6, 10, 14], 46, 80, 0.3),
        "open hat on the offbeat between kicks", DOC_SRC["house_beat"])
    closed16 = [s for s in range(16) if s not in (2, 6, 10, 14)]
    add("DOC-HAT-16", "Closed hat/shaker 16ths around the open hat", steps(closed16, 42, kb_tier, 0.12),
        "straight 16ths with velocity variation and 55-60% swing; velocity tiers from the KB", DOC_SRC["house_beat"] + DOC_SRC["kb"])
    add("DOC-HAT-8TH", "Closed hat straight 8ths", steps(list(range(0, 16, 2)), 42, lambda s: 75 if s % 4 == 0 else 60, 0.15),
        "straight 8ths to reinforce kick and snare (chillout beat)", DOC_SRC["downtempo_beat"])
    add("DOC-TOM-DEEP", "909 tom (deep house)", steps([2, 8, 10], 47, 85, 0.15),
        "tom on the 3rd, 9th and 11th divisions (Rolling Deep House, 125 BPM, swing 60-70)", DOC_SRC["house_beat"])
    add("DOC-AFRO-PERC", "Afro percussion hit", steps([1, 9], 63, 70, 0.15),
        "percussion hit on the 2nd and 10th divisions (Rolling Deep House)", DOC_SRC["house_beat"])
    add("DOC-BASS-OFFBEAT", "Offbeat bass", steps([2, 6, 10, 14], 36, 96, 0.4),
        "one bass note on every offbeat: the kick lands on the beat and the bass answers between", DOC_SRC["house_bass"])
    oct_up = steps([2], 48, 108, 0.4) + steps([6, 10, 14], 36, 94, 0.4)
    add("DOC-BASS-OFFBEAT-OCT", "Offbeat bass, first note an octave up", oct_up,
        "offbeat variation: 'a note on the first hit one octave higher with increased velocity'", DOC_SRC["house_bass"])
    add("DOC-BASS-ROLLING", "Rolling 16ths (kick steps empty)", steps([s for s in range(16) if s % 4 != 0], 36,
        lambda s: 90 if s % 4 == 2 else 62, 0.2), "bass on the three offbeat 16ths of every quarter; the first 16th of each beat left "
        "empty for the kick; the 'and' medium, others quiet", DOC_SRC["techno_rolling_bass"])
    return d


def measured_bass(style: str, n: int = 3, min_notes: int = 3) -> dict[str, dict]:
    """The most typical measured bar patterns of a style's real loops, as library patterns."""
    p = LIB / ("bass_%s.json" % style)
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    lib = json.load(open(p))
    k = 0
    for cell in lib.get("cells", []):
        if len(cell["pattern"]) < min_notes or k >= n:
            continue
        k += 1
        pid = "MEAS-%s-%d" % (style, k)
        notes = [{"start": c["step"] * 0.25, "pitch": 36 + int(c["semi"]), "vel": int(50 + 58 * c["vel"]),
                  "dur": max(0.12, min(float(c["dur"]), 1.5))} for c in cell["pattern"]]
        notes = [n_ for n_ in notes if 24 <= n_["pitch"] <= 60]
        out[pid] = {"id": pid, "name": "Measured bar %d (%s)" % (k, cell["file"][:40]), "bars": 1, "notes": notes,
                    "purpose": "recurring bar of a real %s loop" % style, "genre": style, "tempo_range": [0, 0],
                    "source": {"kind": "measured", "ref": cell["file"], "bpm": cell["bpm"], "typicality": cell["typicality"],
                               "share_of_loop": cell["share"]}}
    return out


def split_by_pitch(p: dict, pid: str, name: str, pitches: set[int]) -> dict:
    return {**p, "id": pid, "name": name, "notes": [n for n in p["notes"] if n["pitch"] in pitches]}


# --- style definitions --------------------------------------------------------------------------------------------------
def styles() -> dict[str, dict]:
    return {
        "techno": {
            "label": "Techno", "bpm": {"default": 128, "min": 124, "max": 134}, "swing_pct": 56, "tonic": "D",
            "arrangement_file": "techno_arrangement.json",
            "element_map": {"drums": ["kick", "clap", "hat"], "percussion": ["perc"], "bass": ["bass"], "texture": ["chords"],
                            "pad": ["pad"], "lead": ["lead"], "melody": ["lead"]},
            "layers": {
                "kick": {"sparse": ["P23"], "base": [["P23"], ["DOC-TECHNO-GHOSTKICK"]], "dense": ["DOC-TECHNO-GHOSTKICK"]},
                "clap": {"sparse": None, "base": [["DOC-CLAP-24"]], "dense": ["DOC-CLAP-24"], "min_energy": 0.5},
                "hat": {"sparse": None, "base": [["P05"]], "dense": ["P05", "P18"], "min_energy": 0.35},
                "perc": {"sparse": None, "base": [["P06"], ["P14"]], "dense": ["P06", "P14"], "min_energy": 0.55},
                "bass": {"sparse": ["B17"], "base": [["B14"], ["B15"], ["MEAS-techno-1"]], "dense": ["B14"]},
                "chords": {"sparse": None, "base": [["S04"], ["G2-23"], ["G2-24"]], "dense": ["G2-24"]},
                "pad": {"sparse": ["G2-21"], "base": [["G2-21"], ["S12"]], "dense": ["G2-22"]},
                "lead": {"sparse": None, "base": [["M06"], ["S07"], ["M10"]], "dense": ["M06"]},
            },
            "fill": ["G2-40"],
            "refs": DOC_SRC["techno_rolling_bass"] + DOC_SRC["rolling_techno_beat"] + DOC_SRC["kb"],
        },
        "house": {
            "label": "House", "bpm": {"default": 124, "min": 120, "max": 128}, "swing_pct": 58, "tonic": "A",
            "arrangement_file": "house_arrangement.json",
            "element_map": {"drums": ["kick", "clap", "hat"], "percussion": ["perc"], "bass": ["bass"], "chords": ["chords"],
                            "pad": ["pad"], "lead": ["lead"], "texture": ["pad"]},
            "layers": {
                "kick": {"sparse": ["DOC-KICK-4OTF"], "base": [["DOC-KICK-4OTF"]], "dense": ["DOC-KICK-4OTF"]},
                "clap": {"sparse": None, "base": [["DOC-CLAP-24"]], "dense": ["DOC-CLAP-24"], "min_energy": 0.4},
                "hat": {"sparse": ["DOC-OHAT-OFFBEAT"], "base": [["DOC-HAT-16", "DOC-OHAT-OFFBEAT"]],
                        "dense": ["DOC-HAT-16", "DOC-OHAT-OFFBEAT"]},
                "perc": {"sparse": None, "base": [["DOC-TOM-DEEP", "DOC-AFRO-PERC"]], "dense": ["DOC-TOM-DEEP", "DOC-AFRO-PERC"],
                         "min_energy": 0.55},
                "bass": {"sparse": ["DOC-BASS-OFFBEAT"], "base": [["DOC-BASS-OFFBEAT-OCT"], ["MEAS-house-1"], ["MEAS-house-2"],
                                                                  ["DOC-BASS-OFFBEAT"]], "dense": ["DOC-BASS-OFFBEAT-OCT"]},
                "chords": {"sparse": None, "base": [["S11"], ["G2-16"], ["G2-15"]], "dense": ["S11"]},
                "pad": {"sparse": ["S03"], "base": [["S03"], ["G2-13"]], "dense": ["S03"]},
                "lead": {"sparse": None, "base": [["M14"]], "dense": ["M14"]},
            },
            "fill": ["G2-41"],
            "refs": DOC_SRC["house_beat"] + DOC_SRC["house_bass"],
        },
        "downtempo": {
            "label": "Downtempo", "bpm": {"default": 90, "min": 80, "max": 100}, "swing_pct": 57, "tonic": "C",
            "arrangement_file": "downtempo_arrangement.json",
            "element_map": {"drums": ["kick", "clap", "hat"], "bass": ["bass"], "chords": ["chords"], "melody": ["lead"],
                            "texture": ["perc"], "pad": ["pad"]},
            "layers": {
                "kick": {"sparse": None, "base": [["P07-KICK"]], "dense": ["P07-KICK"]},
                "clap": {"sparse": None, "base": [["P07-SNARE"], ["DOC-SNARE-24"]], "dense": ["P07-SNARE"], "min_energy": 0.4},
                "hat": {"sparse": None, "base": [["P19"], ["DOC-HAT-8TH"]], "dense": ["DOC-HAT-8TH"], "min_energy": 0.4},
                "perc": {"sparse": ["P24"], "base": [["P08"], ["P24"]], "dense": ["P08", "P24"]},
                "bass": {"sparse": ["B11"], "base": [["B12"], ["B22"], ["MEAS-downtempo-1"], ["B11"]], "dense": ["B12"]},
                "chords": {"sparse": ["S08"], "base": [["S08"], ["S20"], ["G2-15"]], "dense": ["G2-16"]},
                "pad": {"sparse": ["S03"], "base": [["S03"], ["G2-13"]], "dense": ["S03"]},
                "lead": {"sparse": None, "base": [["M05"], ["G2-51"], ["M11"]], "dense": ["M05"]},
            },
            "fill": ["G2-36"],
            "refs": DOC_SRC["downtempo_beat"],
        },
        "electro_cumbia": {
            "label": "Electro cumbia", "bpm": {"default": 100, "min": 88, "max": 108}, "swing_pct": 52, "tonic": "A",
            "arrangement_file": "electro_cumbia_arrangement.json",
            "element_map": {"drums": ["kick", "clap", "hat"], "percussion": ["perc"], "bass": ["bass"], "chords": ["chords"],
                            "melody": ["lead"], "texture": ["pad"], "pad": ["pad"]},
            "layers": {
                "kick": {"sparse": None, "base": [["P03"]], "dense": ["P03"]},
                "clap": {"sparse": None, "base": [["P12"]], "dense": ["P12"], "min_energy": 0.45},
                "hat": {"sparse": ["P01"], "base": [["P01"]], "dense": ["P01"]},
                "perc": {"sparse": ["P25"], "base": [["P02"], ["P25"], ["P17"]], "dense": ["P02", "P16"], "min_energy": 0.0},
                "bass": {"sparse": ["B20"], "base": [["B06"], ["B01"], ["B02"], ["B24"], ["MEAS-electro_cumbia-1"]],
                         "dense": ["B02"]},
                "chords": {"sparse": None, "base": [["S11"], ["G2-12"], ["M01"]], "dense": ["G2-12"]},
                "pad": {"sparse": ["G2-09"], "base": [["G2-09"]], "dense": ["G2-09"]},
                "lead": {"sparse": None, "base": [["S06"], ["S01"], ["M14"], ["M07"]], "dense": ["S06"]},
            },
            "fill": ["P04", "G2-22"],
            "refs": ["https://bassscalespdf.org/blog/how-to-play-cumbia-bass/", "https://en.wikipedia.org/wiki/Tumbao",
                     "knowledge/research/prose_catalog.md (10 traditional cumbia bass rhythms)"],
        },
    }


def arrangement(file: str) -> list[dict]:
    t = (KNOW / "arrangement" / file).read_text()
    try:
        d = json.loads(t)
    except ValueError:                      # two of the owner's files have a '...' where the first section's '{' should be
        d = json.loads(re.sub(r"^\s*\.\.\.\s*$", "    {", t, flags=re.M))
    return [{"name": s["name"], "bars": int(s["bars"]), "elements": s["elements"], "energy": float(s["energy"]),
             "notes": s.get("notes", "")} for s in d["sections"]]


def build() -> dict:
    pats = {}
    pats.update(load_notebooklm())
    pats.update(documented())
    for st in ("techno", "house", "downtempo", "electro_cumbia"):
        pats.update(measured_bass(st))
    # P07 holds the kick and the snare of one break: split it so each can be its own track
    if "P07" in pats:
        pats["P07-KICK"] = split_by_pitch(pats["P07"], "P07-KICK", "Dusty Breakbeat (kick)", {36})
        pats["P07-SNARE"] = split_by_pitch(pats["P07"], "P07-SNARE", "Dusty Breakbeat (snare)", {38})
    st = styles()
    for k, v in st.items():
        v["arrangement"] = arrangement(v.pop("arrangement_file"))
        # fail loudly if a style points at a pattern that does not exist
        for layer, spec in v["layers"].items():
            ids = [i for opt in spec.get("base", []) for i in opt] + (spec.get("sparse") or []) + (spec.get("dense") or [])
            for i in ids:
                if i not in pats:
                    raise KeyError("%s/%s references missing pattern %s" % (k, layer, i))
        for i in v.get("fill", []):
            if i not in pats:
                raise KeyError("%s fill references missing pattern %s" % (k, i))
    return {"schema": "stemforge.styles/1", "patterns": pats, "styles": st}


if __name__ == "__main__":
    out = build()
    (LIB / "styles.json").write_text(json.dumps(out, indent=1))
    kinds = {}
    for p in out["patterns"].values():
        kinds[p["source"]["kind"]] = kinds.get(p["source"]["kind"], 0) + 1
    print("wrote %s: %d patterns %s, styles %s" % (LIB / "styles.json", len(out["patterns"]), kinds, list(out["styles"])))
