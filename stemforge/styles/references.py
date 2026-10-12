"""The real recordings the style library was measured from (this Mac). Provenance only: the app ships the measured JSON."""
from __future__ import annotations

import glob
import os

H = os.path.expanduser("~")
FP = H + "/Documents/ableton projects/SharedAbleton/Factory Packs/"
DESK = H + "/Desktop/"


def _g(pattern: str) -> list[str]:
    return sorted(p for p in glob.glob(pattern) if not os.path.basename(p).startswith("._") and not p.endswith(".asd"))


def bass_references() -> dict[str, list[dict]]:
    """style -> [{path, bpm (None = read from the file name), kind}]. Only files that decode outside Ableton Live."""
    ref: dict[str, list[dict]] = {"electro_cumbia": [], "house": [], "downtempo": [], "techno": []}
    pack = DESK + "Cumbia Bass Beats II- Raza Takeover/"
    for f, bpm in (("emergency cumbia bassline (90bpm).aif", 90), ("salude slap bass (80bpm).aif", 80)):
        if os.path.exists(pack + f):
            ref["electro_cumbia"].append({"path": pack + f, "bpm": bpm, "kind": "loop"})
    # house / dub house: LotusTunes Dub Organica bass grooves (120 BPM), Cymatics bass house (128), Function Loops 120
    lotus = H + "/Documents/ableton projects/SharedAbleton/User Library/LotusTunes Dub Organica Sound Pack/Loops/Bass Grooves/*.wav"
    for p in _g(lotus):
        ref["house"].append({"path": p, "bpm": 120, "kind": "loop"})
    for p in _g(H + "/Documents/ableton projects/ableton samples/Cymatics - House Starter Pack/**/*Bass*128*.wav"):
        ref["house"].append({"path": p, "bpm": 128, "kind": "loop"})
    fl = H + "/Documents/ableton projects/ableton samples/Function Loops - Funk Soul & Rnb - Free Gift/FL_Loops/"
    for f, bpm in (("FL_FMT_Kit02_120_Bass_Loop_02_Amin.wav", 120),):
        if os.path.exists(fl + f):
            ref["house"].append({"path": fl + f, "bpm": bpm, "kind": "loop"})
    # downtempo: Cymatics Eternity lofi/classic bass loops (80-100), Function Loops 84-108, Playbeat 90s, AMM2 bass 77-96
    cy = H + "/Documents/ableton projects/ableton samples/Cymatics - Eternity Sample Pack/**/*Bass*.wav"
    for p in _g(cy):
        b = None
        import re as _re
        m = _re.search(r"(\d{2,3}) BPM", os.path.basename(p))
        b = int(m.group(1)) if m else None
        if b and 78 <= b <= 105:
            ref["downtempo"].append({"path": p, "bpm": b, "kind": "loop"})
    for f, bpm in (("FL_RSC_Kit05_Bass_Loop_84_C#.wav", 84), ("FL_RSC_Kit04_Bass_Loop_91_D.wav", 91), ("FL_FMT_Kit01_108_Bass_Loop_EbMaj.wav", 108)):
        if os.path.exists(fl + f):
            ref["downtempo"].append({"path": fl + f, "bpm": bpm, "kind": "loop"})
    pb = H + "/Music/Audiomodern/Playbeat 4/Factory Samples/"
    for f, bpm in (("90_D_Bass_Loop_19.flac", 90), ("90_Db_Bass_Loop_22.flac", 90), ("90_Eb_Bass_Loop_05.flac", 90),
                   ("AMM2_BASS_E_96bpm(3).flac", 96), ("AMM2_BASS_G#_77bpm_4(2).flac", 77)):
        if os.path.exists(pb + f):
            ref["downtempo"].append({"path": pb + f, "bpm": bpm, "kind": "loop"})
    return ref
