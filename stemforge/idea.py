"""Read the IDEA of a song from its analysed stems: key colour, groove, structure, bass movement.

This is the "brief" that `compose` writes new parts from. Everything here is MEASURED from the audio or from the
reliable transcriptions (drums, percussion, mono bass). Polyphonic note guesses (keys, synth) are deliberately NOT used for
pitch: they are about 40% right, so only the audio chroma of those stems is used, which is stable.
"""
from __future__ import annotations

import numpy as np

PC_NAMES = "C C# D D# E F F# G G# A A# B".split()
BEATS_PER_BAR = 4


def _chroma(path: str) -> np.ndarray:
    """Long-window STFT chroma (resolves a 37 Hz sub; a CQT smears it into the neighbouring semitones), tuning-corrected."""
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    tun = librosa.estimate_tuning(y=y, sr=sr, n_fft=16384)
    ch = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=16384, hop_length=4096, tuning=tun, n_chroma=12).mean(axis=1)
    return ch / max(ch.sum(), 1e-9)


def measure_swing(path: str, beats_s: list[float]) -> dict:
    """Swing of the 16ths in % (50 = straight, 66.7 = triplet), measured against the song's OWN on-beat peak so a
    constant grid offset or detector latency does not count as swing. 'e' and 'a' are measured separately."""
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time", hop_length=128)
    b = np.asarray(beats_s)
    fr = []
    for t in onsets:
        i = np.searchsorted(b, t) - 1
        if 0 <= i < len(b) - 1:
            fr.append((t - b[i]) / (b[i + 1] - b[i]))
    fr = np.asarray(fr)
    near0 = fr[(fr < 0.15) | (fr > 0.92)]
    near0 = np.where(near0 > 0.5, near0 - 1.0, near0)
    e, a = fr[(fr >= 0.18) & (fr <= 0.42)], fr[(fr >= 0.68) & (fr <= 0.92)]
    if len(near0) < 30 or len(e) < 30:
        return {"swing_pct": 50.0, "evidence_onsets": int(len(fr)), "note": "too little evidence: assuming straight"}
    ref = float(np.median(near0))
    e_pos = float(np.median(e)) - ref
    out = {"swing_pct": round(100.0 * e_pos / 0.5, 1), "e_position_beats": round(e_pos, 3),
           "evidence_onsets": int(len(e) + len(a)), "grid_offset_beats": round(ref, 3)}
    if len(a) >= 30:
        out["a_position_beats"] = round(float(np.median(a)) - ref, 3)
    return out


def layer_profile(path: str, beats_s: list[float], sections: list[dict], grid_offset: float = 0.0) -> dict[int, dict]:
    """Per section: how often and WHERE (16-step positions) a harmonic stem really hits, how hard, and which pitch
    classes it sustains. Timing and dynamics come from the audio; pitch classes come from a long-window chroma."""
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = 256
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop)
    t_on = librosa.frames_to_time(frames, sr=sr, hop_length=hop)
    strength = env[frames] / max(float(np.percentile(env, 99)), 1e-9)
    tun = librosa.estimate_tuning(y=y, sr=sr, n_fft=16384)
    ch = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=16384, hop_length=4096, tuning=tun, n_chroma=12)
    t_ch = librosa.frames_to_time(np.arange(ch.shape[1]), sr=sr, hop_length=4096)
    rms = librosa.feature.rms(y=y, hop_length=4096)[0]
    b = np.asarray(beats_s)
    out: dict[int, dict] = {}
    for sec in sections:
        i0, i1 = sec["start_bar"] * BEATS_PER_BAR, (sec["start_bar"] + sec["length_bars"]) * BEATS_PER_BAR
        if i1 >= len(b):
            i1 = len(b) - 1
        t0, t1 = float(b[i0]), float(b[i1])
        sel = (t_on >= t0) & (t_on < t1)
        steps = np.zeros(16)
        for t, st in zip(t_on[sel], strength[sel]):
            j = np.searchsorted(b, t) - 1
            if j < 0 or j >= len(b) - 1:
                continue
            ph = ((t - b[j]) / (b[j + 1] - b[j]) - grid_offset) % 1.0
            beat_in_bar = j % BEATS_PER_BAR
            steps[int(round((beat_in_bar + ph) * 4)) % 16] += st
        c = (t_ch >= t0) & (t_ch < t1)
        cw = ch[:, c].mean(axis=1) if c.any() else np.zeros(12)
        r = rms[(t_ch >= t0) & (t_ch < t1)]
        bars = max(sec["length_bars"], 1)
        out[sec["index"]] = {
            "onsets_per_bar": round(float(sel.sum()) / bars, 2),
            "step_weights": [round(float(x / max(steps.sum(), 1e-9)), 3) for x in steps],
            "mean_strength": round(float(strength[sel].mean()) if sel.any() else 0.0, 3),
            "level_db": round(float(20 * np.log10(max(float(r.mean()) if r.size else 1e-6, 1e-6))), 1),
            "chroma": [round(float(x), 3) for x in (cw / max(cw.sum(), 1e-9))],
        }
    return out


def _section_role(sec: dict) -> str:
    label = (sec.get("label") or "").lower()
    for key in ("intro", "outro", "build", "breakdown", "peak", "groove"):
        if key in label:
            return key
    return "groove"


def bass_by_section(bp: dict, stem: str) -> dict[int, list[dict]]:
    """Absolute-beat notes of one stem grouped by section index (from the clips placed in each section)."""
    clips = {c["id"]: c for c in bp["clips"]}
    secs = {s["index"]: s for s in bp["sections"]}
    out: dict[int, list[dict]] = {}
    for p in bp["placements"]:
        if p["stem"] != stem:
            continue
        base = secs[p["section"]]["start_bar"] * BEATS_PER_BAR
        out[p["section"]] = [{**n, "abs": base + n["start"]} for n in clips[p["clip"]]["notes"]]
    return out


def extract(bp: dict, log=print) -> dict:
    g = bp["global"]
    folder_audio = {s["name"]: s["path"] for s in bp["stems"]}
    roles = {s["name"]: s["role"] for s in bp["stems"]}
    bass = next((n for n, r in roles.items() if r == "bass"), None)
    keys = [n for n, r in roles.items() if r in ("keys", "synth")]

    # --- tonal palette from audio chroma (bass counted double: it is the most reliable witness of the root)
    pcs = np.zeros(12)
    if bass:
        pcs += 2 * _chroma(folder_audio[bass])
    for k in keys:
        pcs += _chroma(folder_audio[k])
    pcs = pcs / pcs.sum()
    tonic = int(np.argmax(pcs))
    rel = {PC_NAMES[(tonic + i) % 12]: round(float(pcs[(tonic + i) % 12]), 3) for i in range(12)}
    third_min, third_maj = float(pcs[(tonic + 3) % 12]), float(pcs[(tonic + 4) % 12])
    fifth, flat2 = float(pcs[(tonic + 7) % 12]), float(pcs[(tonic + 1) % 12])
    maj7, tritone = float(pcs[(tonic + 11) % 12]), float(pcs[(tonic + 6) % 12])
    third_clear = max(third_min, third_maj) > 0.09
    # pitch classes that are just overtones of the root / fifth (harmonics 3,5,7 of D and A) are not "notes played"
    def _pc(semi):
        return (tonic + semi) % 12
    overtones = {_pc(0), _pc(7), _pc(4), _pc(2), _pc(11), _pc(10)}      # R, 5, M3(h5), 9(h9), 7(h15 of R / h5 of 5), b7(h7)
    colour = [PC_NAMES[i] for i in np.argsort(pcs)[::-1] if i not in overtones and pcs[i] > 0.05][:2]
    palette = [PC_NAMES[i] for i in np.argsort(pcs)[::-1][:7]]
    key = {
        "tonic": PC_NAMES[tonic], "tonic_pc": tonic, "pc_weights": rel, "palette_ranked": palette,
        "fifth": round(fifth, 3), "minor_third": round(third_min, 3), "major_third": round(third_maj, 3),
        "flat_second": round(flat2, 3), "leading_tone": round(maj7, 3), "tritone": round(tritone, 3),
        "has_clear_third": bool(third_clear),
        "colour_tones": colour,
        "reading": ("%s drone with open fifth (%s); no stable third in the sustained material (minor %.2f, major %.2f). "
                    "Real colour beyond the overtones: %s%s"
                    % (PC_NAMES[tonic], PC_NAMES[_pc(7)], third_min, third_maj, "/".join(colour) or "none",
                       "; flat 2nd present = Phrygian lean" if flat2 > 0.06 else "")),
        "analyzer_said": g.get("key"),
    }

    # --- groove
    perc = next((n for n, r in roles.items() if r == "drums" and "perc" in n.lower()), None)
    groove = measure_swing(folder_audio[perc], g["beats_s"]) if perc else {"swing_pct": 50.0, "evidence_onsets": 0}

    # --- structure + bass movement per section
    bass_notes = bass_by_section(bp, bass) if bass else {}
    sections = []
    for s in bp["sections"]:
        bars = s["length_bars"]
        notes = bass_notes.get(s["index"], [])
        roots = []
        steps = np.zeros(16)
        for b in range(bars):
            lo = (s["start_bar"] + b) * BEATS_PER_BAR
            h = np.zeros(12)
            for n in notes:
                if lo <= n["abs"] < lo + BEATS_PER_BAR:
                    h[n["pitch"] % 12] += n["duration"]
                    steps[int(round((n["abs"] - lo) / 0.25)) % 16] += 1
            roots.append(PC_NAMES[int(np.argmax(h))] if h.sum() > 0 else None)
        denom = max(steps.sum(), 1)
        sections.append({
            "index": s["index"], "name": s["name"], "label": s["label"], "role": _section_role(s),
            "start_bar": s["start_bar"], "length_bars": bars, "energy_db": s["energy_db"],
            "energy_slope_db_per_bar": s["energy_slope_db_per_bar"], "active_stems": s["active_stems"],
            "bass_roots_by_bar": roots, "bass_step_probs": [round(float(x / denom), 3) for x in steps],
            "bass_notes_per_bar": round(len(notes) / max(bars, 1), 2),
        })
    layers: dict = {}
    for k in keys:
        log("reading the rhythm of %s" % k)
        layers[k] = layer_profile(folder_audio[k], g["beats_s"], bp["sections"], groove.get("grid_offset_beats", 0.0))
    return {"schema": "stemforge.idea/1", "layers": layers, "song": bp["song"]["name"], "tempo": g["tempo"], "bars": g["n_bars"],
            "time_signature": g["time_signature"], "key": key, "groove": groove, "sections": sections,
            "roles": roles, "bass_stem": bass}


def _short(name: str) -> str:
    """'3 Keyboard' -> 'Keyboard'; plain names ('bass') stay as they are."""
    head, _, rest = name.partition(" ")
    return rest if head.isdigit() and rest else name


def production_notes(tempo: float, tonic: str = "D") -> list[str]:
    """Tempo-synced numbers from the owner's NotebookLM base (knowledge/HYPNOTIC_TECHNO_NOTEBOOKLM_KNOWLEDGE_BASE.md).
    They are for the mix and the sound design; Stemforge writes MIDI only."""
    sixteenth = 15000.0 / tempo
    return [
        "Delay on keys/stabs: dotted 1/8 = %.0f ms (20%% feedback, 3-4 repeats); 1/16 = %.0f ms." % (sixteenth * 3, sixteenth),
        "Kick sidechain on the rumble/pads: attack 1 ms, release 27-55 ms, or one 1/16 = %.0f ms; 8-12 dB of reduction." % sixteenth,
        "Everything below ~120 Hz mono; keep the sub (the bass sits on %s0, about 37 Hz) and the kick out of each other's way:"
        " notch the kick's fundamental in the sub, or tune the kick to F/F# (44-48 Hz) as your base suggests." % tonic,
        "Kick and sub stay 100% on the grid; tops carry the swing (measured below). Offbeat hats 5-15 ms laid back is a good start.",
        "Peak = denser, not louder: more layers, a slightly faster hat, a longer reverb tail. Test the loop with the "
        "'walk out of the room' rule: if it still holds through the wall, the groove is right.",
    ]


def to_markdown(idea: dict) -> str:
    k, gr = idea["key"], idea["groove"]
    L = ["# Song idea: %s" % idea["song"], "",
         "- **Tempo** %.2f BPM, %d bars, %d/%d" % (idea["tempo"], idea["bars"], *idea["time_signature"]),
         "- **Key colour** %s" % k["reading"],
         "- **Palette (strongest first)** %s" % ", ".join(k["palette_ranked"]),
         "- **Fifth** %.2f, **flat 2nd** %.2f, **leading tone** %.2f, **tritone** %.2f" % (
             k["fifth"], k["flat_second"], k["leading_tone"], k["tritone"]),
         "- **Swing** %.1f%% on the 16ths ('e' at %.2f beat instead of 0.25; %s onsets measured)" % (
             gr["swing_pct"], gr.get("e_position_beats", 0.25), gr["evidence_onsets"]),
         "- The analyzer's own guess was %s %s (confidence %.2f); the audio shows no clear third, so the %s is not used." % (
             k["analyzer_said"]["tonic"], k["analyzer_said"]["mode"], k["analyzer_said"]["confidence"],
             k["analyzer_said"]["mode"]),
         "", "| # | section | role | bars | energy dB | layers | bass roots (per bar) |", "|---|---|---|---|---|---|---|"]
    for s in idea["sections"]:
        roots = [r for r in s["bass_roots_by_bar"] if r]
        uniq = sorted(set(roots), key=roots.index)
        L.append("| %d | %s | %s | %d | %.1f | %s | %s |" % (
            s["index"] + 1, s["label"].upper(), s["role"], s["length_bars"], s["energy_db"],
            ", ".join(_short(n) for n in s["active_stems"]), " ".join(uniq) or "-"))
    L += ["", "## Sound and mix notes (from your NotebookLM base, tempo-synced)", ""]
    L += ["- " + x for x in production_notes(idea["tempo"], idea["key"]["tonic"])]
    return "\n".join(L) + "\n"
