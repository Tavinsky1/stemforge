"""Rebuild a pitched stem as clean MIDI straight from its own audio. No randomness, no templates.

Why this exists: polyphonic note transcribers (Basic Pitch) read the harmonics of a synth as extra notes and miss half the
hits, and hand-written pattern generators do not know the song. A drone-based techno layer is simple enough to decode
directly:

1. WHEN: every hit comes from onset detection on the stem (a CQT-based novelty curve), placed on the song's beat grid and
   snapped to the nearest 16th *including the song's measured swing positions* ('e' and 'a' sit later than 0.25/0.75).
2. WHAT: the pitch of each hit is decoded by harmonic summation (a pitch gets credit for its own energy plus its 2nd..6th
   harmonics), so the 3rd harmonic of a D is not mistaken for an A. Further notes are found after subtracting what the first
   pitch explains, up to `max_poly`.
3. HOW HARD: the onset strength of each hit, scaled per stem, becomes velocity.
4. CLEAN LOOPS: within a section, bars whose 16-step patterns are alike are merged into their majority pattern (a step
   stays if most of the bars in its cluster have it, with the most common pitch). Detector noise and delay tails vanish;
   fills and variations that really happen stay, because they are not alike enough to be merged.
"""
from __future__ import annotations

import numpy as np

BEATS_PER_BAR = 4
HARMONICS = [(1, 0), (2, 12), (3, 19), (4, 24), (5, 28), (6, 31)]
HARM_DECAY = 0.82


def _load(path: str, sr: int = 22050):
    import librosa
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y, sr


def _cqt(y: np.ndarray, sr: int, m0: int = 28, n_bins: int = 92, hop: int = 256):
    import librosa
    tun = float(librosa.estimate_tuning(y=y, sr=sr, n_fft=16384))
    C = np.abs(librosa.cqt(y, sr=sr, hop_length=hop, fmin=librosa.midi_to_hz(m0), n_bins=n_bins, bins_per_octave=12,
                           tuning=tun))
    return C, tun


def _salience(mag: np.ndarray) -> np.ndarray:
    """mag: (n_bins,) magnitude per semitone bin -> salience of each bin as a fundamental."""
    n = len(mag)
    s = np.zeros(n)
    for k, (h, off) in enumerate(HARMONICS):
        w = HARM_DECAY ** k
        if off < n:
            s[: n - off] += w * mag[off:]
    return s


MIN_SEP = 3          # semitones: closer bins are leakage of detuned unison, not another note
OWN_ENERGY = 0.4     # a fundamental must have this share of its octave's energy (harmonic sums prefer the lowest octave)


def _decode_pitches(mag: np.ndarray, m0: int, lo: int, hi: int, max_poly: int) -> list[tuple[int, float]]:
    """Up to max_poly (midi, salience) fundamentals inside [lo, hi], strongest first. Harmonics of a chosen pitch are
    removed before the next one is picked, so a single note never turns into a stack."""
    work = np.sqrt(mag.copy())
    out: list[tuple[int, float]] = []
    first = None
    for _ in range(max_poly):
        s = _salience(work)
        idx = np.arange(len(s)) + m0
        s[(idx < lo) | (idx > hi)] = 0.0
        # a candidate must be audible itself, not only implied by its overtones
        for j in range(len(s)):
            if s[j] > 0 and j + 12 < len(work) and work[j] < OWN_ENERGY * work[j + 12]:
                s[j] = 0.0
        for q, _ in out:                                   # leakage guard around notes already chosen
            a, b = max(q - m0 - MIN_SEP + 1, 0), min(q - m0 + MIN_SEP, len(s))
            s[a:b] = 0.0
        j = int(np.argmax(s))
        if s[j] <= 0:
            break
        if first is None:
            first = s[j]
        elif s[j] < 0.55 * first:
            break
        out.append((j + m0, float(s[j])))
        for k, (h, off) in enumerate(HARMONICS):
            b = j + off
            if b < len(work):
                work[b] *= 0.25
        work[j] = 0.0
    return out


def _onset_times(C: np.ndarray, sr: int, hop: int, y: np.ndarray):
    import librosa
    env = librosa.onset.onset_strength(S=librosa.amplitude_to_db(C, ref=np.max), sr=sr, hop_length=hop, lag=2, max_size=3)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop, backtrack=False,
                                        pre_max=3, post_max=3, pre_avg=12, post_avg=12, delta=0.12, wait=3)
    t = librosa.frames_to_time(frames, sr=sr, hop_length=hop)
    p95 = float(np.percentile(env, 99)) or 1.0
    return t, np.asarray(env)[frames] / p95, env


def snap_outliers(events: list[dict], rare: float = 0.04, lead: float = 0.5) -> int:
    """In a drone riff a rare note one semitone from the dominant pitch is a tracking error, not a note: snap it.
    Only when the dominant pitch carries more than `lead` of the hits and the neighbour less than `rare`. Returns how many."""
    from collections import Counter
    if not events:
        return 0
    cnt = Counter(e["pitches"][0][0] for e in events)
    dom, n_dom = cnt.most_common(1)[0]
    total = sum(cnt.values())
    if n_dom / total < lead:
        return 0
    changed = 0
    for e in events:
        p0 = e["pitches"][0][0]
        if abs(p0 - dom) == 1 and cnt[p0] / total < rare:
            e["pitches"] = [(dom, e["pitches"][0][1])] + e["pitches"][1:]
            changed += 1
    return changed


def snap_step(t: float, beats: np.ndarray, grid_offset: float, e_pos: float, a_pos: float) -> tuple[int, int, float] | None:
    """(beat index, step 0..3 within the beat, signed error in beats) of the nearest swung 16th, or None outside the grid."""
    j = int(np.searchsorted(beats, t)) - 1
    if j < 0 or j >= len(beats) - 1:
        return None
    ph = (t - beats[j]) / (beats[j + 1] - beats[j]) - grid_offset
    cands = [0.0, e_pos, 0.5, a_pos, 1.0]
    k = int(np.argmin([abs(ph - c) for c in cands]))
    if k == 4:                      # rounds up to the next beat's downbeat
        return j + 1, 0, ph - 1.0
    return j, k, ph - cands[k]


F0_HOP = 512


def _f0_track(y: np.ndarray, sr: int, lo: int, hi: int):
    """Fundamental of a mono-ish layer by periodicity (pyin). Unlike a sum of harmonics it follows the period, so a
    note whose fundamental was filtered away is still read at its true octave."""
    import librosa
    f0, voiced, _ = librosa.pyin(y, fmin=float(librosa.midi_to_hz(max(lo - 2, 24))), fmax=float(librosa.midi_to_hz(hi + 2)),
                                 sr=sr, hop_length=F0_HOP)
    midi = np.where(voiced & ~np.isnan(f0), librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0)), np.nan)
    return midi, librosa.frames_to_time(np.arange(len(midi)), sr=sr, hop_length=F0_HOP)


def _pitch_at(midi: np.ndarray, times: np.ndarray, t: float, win=(0.03, 0.14)):
    sel = (times >= t + win[0]) & (times <= t + win[1])
    v = midi[sel]
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    return int(round(float(np.median(v))))


def extract_events(path: str, beats_s, groove: dict, lo: int, hi: int, max_poly: int = 1, min_strength: float = 0.18,
                   win=(0.025, 0.11), use_f0: bool = True) -> list[dict]:
    """Every hit of the stem as {beat, step, strength, pitches, t}. `beat` is an absolute beat index (bar*4+beat).

    Pitch comes from the fundamental tracker (pyin) when `use_f0`, with harmonic-salience decoding as the fallback for
    hits where the tracker is silent (and always for max_poly > 1)."""
    y, sr = _load(path)
    hop = 256
    m0 = 24                                   # C1: the sub of a D1 bass (37 Hz) must be inside the analysed range
    C, _ = _cqt(y, sr, m0=m0, n_bins=96, hop=hop)
    t_on, strength, env = _onset_times(C, sr, hop, y)
    f0_midi = f0_times = None
    if use_f0 and max_poly == 1:
        f0_midi, f0_times = _f0_track(y, sr, lo, hi)
    last_pitch = None
    beats = np.asarray(beats_s)
    go = float(groove.get("grid_offset_beats", 0.0))
    e = float(groove.get("e_position_beats", 0.25))
    a = float(groove.get("a_position_beats", 0.75))
    ev: dict[tuple[int, int], dict] = {}
    t_list = [float(x) for x in t_on]
    for idx, (t, st) in enumerate(zip(t_on, strength)):
        if st < min_strength:
            continue
        # the analysis window must end before the NEXT hit's attack, or two hits a 16th apart blur into one wrong pitch
        gap = (t_list[idx + 1] - float(t)) if idx + 1 < len(t_list) else 1.0
        w_end = max(win[0] + 0.03, min(win[1], gap - 0.012))
        pos = snap_step(float(t), beats, go, e, a)
        if pos is None:
            continue
        j, k, err = pos
        if abs(err) > 0.16:                       # not close to any 16th: a flam or a tail, not a step
            continue
        f0, f1 = int((t + win[0]) * sr / hop), int((t + w_end) * sr / hop) + 1
        seg = C[:, f0:max(f1, f0 + 1)]
        if seg.size == 0:
            continue
        pitches = []
        if f0_midi is not None:
            p0 = _pitch_at(f0_midi, f0_times, float(t), win=(0.03, max(0.06, w_end + 0.03)))
            if p0 is not None and lo <= p0 <= hi:
                pitches = [(p0, 1.0)]
        if not pitches:
            mag = seg.mean(axis=1)
            pitches = _decode_pitches(mag, m0, lo, hi, max_poly)
        if not pitches and last_pitch is not None:
            pitches = [(last_pitch, 0.0)]                 # a mono riff keeps its note through an unvoiced attack
        if not pitches:
            continue
        last_pitch = pitches[0][0]
        p_top = pitches[0][0]
        rows = [r for r in (p_top - m0, p_top + 12 - m0) if 0 <= r < C.shape[0]]
        level = float(seg[rows].max()) if rows else float(seg.max())
        level_db = 20.0 * np.log10(max(level, 1e-6))
        key = (j, k)
        if key not in ev or st > ev[key]["strength"]:
            ev[key] = {"beat": j, "step": k, "strength": float(st), "pitches": pitches, "t": float(t),
                       "level_db": level_db}
    out = [ev[k] for k in sorted(ev)]
    # how long each hit really rings: its own energy (fundamental or 2nd harmonic) until it falls to 35% or the next hit
    beat_len = float(np.median(np.diff(beats)))
    for i, e in enumerate(out):
        p = e["pitches"][0][0]
        rows = [r for r in (p - m0, p + 12 - m0) if 0 <= r < C.shape[0]]
        f_on = int(e["t"] * sr / hop)
        nxt_t = out[i + 1]["t"] if i + 1 < len(out) else e["t"] + 2.0
        f_end = min(int((min(nxt_t, e["t"] + 2.0)) * sr / hop), C.shape[1])
        if not rows or f_end <= f_on + 1:
            e["dur"] = 0.25
            continue
        env = C[rows, f_on:f_end].max(axis=0)
        pk = float(env[: max(3, len(env) // 4)].max()) or 1.0
        below = np.nonzero(env < 0.35 * pk)[0]
        sec = (below[0] if len(below) else len(env)) * hop / sr
        e["dur"] = float(np.clip(sec / beat_len, 0.1, 2.0))
    return out


def step_of(e: dict) -> int:
    return (e["beat"] % BEATS_PER_BAR) * 4 + e["step"]


def bar_of(e: dict) -> int:
    return e["beat"] // BEATS_PER_BAR


def clean_loops(events: list[dict], start_bar: int, n_bars: int, similarity: float = 0.72, vote: float = 0.5) -> list[dict]:
    """Merge alike bars into their majority pattern. Returns new events for bars start_bar .. start_bar+n_bars-1."""
    by_bar: dict[int, list[dict]] = {b: [] for b in range(start_bar, start_bar + n_bars)}
    for e in events:
        b = bar_of(e)
        if b in by_bar:
            by_bar[b].append(e)
    vec = {}
    for b, es in by_bar.items():
        v = np.zeros(16)
        for e in es:
            v[step_of(e)] = e["strength"]
        vec[b] = v

    def sim(a: np.ndarray, c: np.ndarray) -> float:
        ab = (a > 0)
        cb = (c > 0)
        u = (ab | cb).sum()
        return 1.0 if u == 0 else float((ab & cb).sum() / u)       # Jaccard on which steps are hit

    clusters: list[list[int]] = []
    for b in range(start_bar, start_bar + n_bars):
        if not by_bar[b]:
            clusters.append([b])
            continue
        placed = False
        for cl in clusters:
            ref = vec[cl[0]]
            if ref.any() and sim(vec[b], ref) >= similarity:
                cl.append(b)
                placed = True
                break
        if not placed:
            clusters.append([b])
    out: list[dict] = []
    for cl in clusters:
        if len(cl) == 1:
            out.extend(by_bar[cl[0]])
            continue
        # majority pattern of the cluster
        for s in range(16):
            hits = [e for b in cl for e in by_bar[b] if step_of(e) == s]
            if len(hits) / len(cl) < vote:
                continue
            strength = float(np.median([h["strength"] for h in hits]))
            level_db = float(np.median([h.get("level_db", -60.0) for h in hits]))
            dur = float(np.median([h.get("dur", 0.25) for h in hits]))
            # most common top pitch among the hits at this step
            tops = [h["pitches"][0][0] for h in hits]
            top = max(set(tops), key=tops.count)
            chord = max((h for h in hits if h["pitches"][0][0] == top), key=lambda h: len(h["pitches"]))
            for b in cl:
                e0 = chord
                out.append({"beat": b * BEATS_PER_BAR + s // 4, "step": s % 4, "strength": strength,
                            "pitches": e0["pitches"], "t": 0.0, "dur": dur, "level_db": level_db})
    return sorted(out, key=lambda e: (e["beat"], e["step"]))


def fold_octave(p: int, lo: int, hi: int) -> int:
    while p < lo:
        p += 12
    while p > hi:
        p -= 12
    return p


def velocity_map(strengths: list[float], lo: int = 46, hi: int = 118):
    """Rank-based: the softest hits of the stem get `lo`, the hardest `hi`; the shape of the dynamics is kept."""
    srt = np.sort(np.asarray(strengths, float)) if len(strengths) else np.array([0.0, 1.0])

    def f(x: float) -> int:
        r = float(np.searchsorted(srt, x)) / max(len(srt) - 1, 1)
        return int(round(lo + (hi - lo) * min(max(r, 0.0), 1.0)))
    return f


def to_notes(events: list[dict], start_bar: int, n_bars: int, swing_pct: float, vel_fn=None, octave: int = 0,
             gate: float = 0.92, min_dur: float = 0.1) -> list[dict]:
    """Section-relative MIDI notes. Start = beat + step*0.25 (+ swing offset on the 'e'/'a'). Length is what the hit really
    rings in the stem (never past the next hit). `octave` shifts the whole layer by whole octaves."""
    off = max(0.0, (swing_pct / 100.0 - 0.5) * 0.5)
    base = start_bar * BEATS_PER_BAR
    evs = [e for e in events if start_bar <= bar_of(e) < start_bar + n_bars]
    evs.sort(key=lambda e: (e["beat"], e["step"]))
    notes: list[dict] = []
    for i, e in enumerate(evs):
        t0 = (e["beat"] - base) + e["step"] * 0.25 + (off if e["step"] in (1, 3) else 0.0)
        nxt = (evs[i + 1]["beat"] - base) + evs[i + 1]["step"] * 0.25 if i + 1 < len(evs) else n_bars * BEATS_PER_BAR
        room = max(nxt - t0 - 0.02, min_dur)
        dur = max(min_dur, min(float(e.get("dur", 0.25)), room)) * gate
        vel = vel_fn(e.get("level_db", e["strength"])) if vel_fn else int(round(46 + 72 * min(1.0, e["strength"])))
        for p, _s in e["pitches"]:
            notes.append({"pitch": int(min(127, max(0, p + 12 * octave))), "start": round(t0, 4), "duration": round(dur, 3),
                          "velocity": vel, "confidence": 1.0, "source": "resynth"})
    return notes


# ---- the rebuild of a whole song -------------------------------------------------------------------------------------
LAYERS = {"bass": ("R Bass", 24, 62), "keys": ("R Keys", 30, 90), "synth": ("R Synth", 30, 96)}
REBUILT = tuple(v[0] for v in LAYERS.values())
RULES = [
    "Every hit's time comes from the stem's own audio, snapped to the 16th grid with the song's measured swing.",
    "Every hit's pitch is the stem's fundamental at that moment (period tracker), at the register the song uses.",
    "Velocity is the hit's loudness ranked within the stem; note length is how long the hit really rings.",
    "Bars that repeat are merged into their majority pattern, so delay tails and detector noise disappear; fills stay.",
    "A layer is written wherever it audibly plays, including quiet sections up to 11 dB below its own level; true silence stays silent.",
    "Nothing is random: the same stems give the same MIDI.",
]


QUIET_DB = 11.0        # a layer still counts as playing up to this far below its own median hit level
MIN_HITS_PER_BAR = 2.0


def _layer_plays(events: list[dict], sec: dict, analyzer_says_active: bool) -> bool:
    """Is the layer audibly playing in this section? Trust the analyzer when it says yes. When it says no, still
    count a quiet layer that keeps hitting (a part that sits 8-10 dB lower is part of the song), but not true silence."""
    if analyzer_says_active:
        return True
    lo, hi = sec["start_bar"], sec["start_bar"] + sec["length_bars"]
    es = [e for e in events if lo <= e["beat"] // BEATS_PER_BAR < hi]
    if not es or len(es) / max(sec["length_bars"], 1) < MIN_HITS_PER_BAR:
        return False
    med_all = float(np.median([e.get("level_db", 0.0) for e in events])) if events else 0.0
    med_sec = float(np.median([e.get("level_db", 0.0) for e in es]))
    return med_sec >= med_all - QUIET_DB


def _stem_fingerprint(path: str) -> str:
    import os
    st = os.stat(path)
    return "%d:%d" % (st.st_size, int(st.st_mtime))


def rebuild(bp: dict, idea: dict, log=print, straight: bool = False, octaves: dict | None = None,
            cache_path: str | None = None, roles=("bass", "keys", "synth")) -> dict:
    """A new blueprint: drum-mode stems as transcribed (16ths re-swung), Bass/Keys/Synth rebuilt from their audio."""
    import copy
    import json
    import os
    from .compose import apply_swing

    octaves = octaves or {}
    out = copy.deepcopy(bp)
    groove = dict(idea["groove"])
    swing = 50.0 if straight else float(groove["swing_pct"])
    if straight:
        groove = {**groove, "e_position_beats": 0.25, "a_position_beats": 0.75}
    cache: dict = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path))
        except (OSError, ValueError):
            cache = {}
    secs = idea["sections"]
    n_bars_total = max(s["start_bar"] + s["length_bars"] for s in secs)
    drum_stems = [s for s in bp["stems"] if s.get("mode") == "drums"]
    drum_names = {s["name"] for s in drum_stems}
    clip_by_id = {c["id"]: c for c in bp["clips"]}
    clips, placements, stems = [], [], []
    for p in bp["placements"]:
        if p["stem"] not in drum_names:
            continue
        c = clip_by_id[p["clip"]]
        nid = "%s|%d" % (p["stem"], p["section"])
        clips.append({**copy.deepcopy(c), "id": nid, "notes": apply_swing(c["notes"], swing), "used_in": [p["section"]]})
        placements.append({"stem": p["stem"], "section": p["section"], "clip": nid})
    stems += [copy.deepcopy(s) for s in drum_stems]
    report = {}
    for role in roles:
        src = next((s for s in bp["stems"] if s["role"] == role and s.get("path")), None)
        if src is None:
            continue
        name, lo, hi = LAYERS[role]
        key = "%s|%s|%s|%.3f|%.3f|v3" % (src["name"], _stem_fingerprint(src["path"]), straight,
                                         groove.get("e_position_beats", 0.25), groove.get("grid_offset_beats", 0.0))
        if key in cache:
            events = cache[key]
            for e in events:
                e["pitches"] = [tuple(x) for x in e["pitches"]]
            log("%s: using the saved reading of %s" % (name, src["name"]))
        else:
            log("%s: reading every hit of %s (about a minute)..." % (name, src["name"]))
            events = extract_events(src["path"], bp["global"]["beats_s"], groove, lo, hi)
            cache = {k: v for k, v in cache.items() if not k.startswith(src["name"] + "|")}
            cache[key] = [{**e, "pitches": [list(x) for x in e["pitches"]]} for e in events]
            if cache_path:
                json.dump(cache, open(cache_path, "w"))
        fixed = snap_outliers(events)
        if fixed:
            log("%s: %d rare notes one semitone off the main pitch were tracking errors and were snapped" % (name, fixed))
        vel = velocity_map([e.get("level_db", e["strength"]) for e in events])
        n_notes = 0
        for s in secs:
            if not _layer_plays(events, s, src["name"] in s["active_stems"]):
                continue
            cleaned = clean_loops(events, s["start_bar"], s["length_bars"])
            notes = to_notes(cleaned, s["start_bar"], s["length_bars"], swing, vel_fn=vel, octave=int(octaves.get(role, 0)))
            if not notes:
                continue
            cid = "%s|%d" % (name, s["index"])
            clips.append({"id": cid, "stem": name, "name": "%s %s" % (name, s["label"]),
                          "length_beats": s["length_bars"] * BEATS_PER_BAR, "notes": notes, "loop_period_bars": None,
                          "used_in": [s["index"]]})
            placements.append({"stem": name, "section": s["index"], "clip": cid})
            n_notes += len(notes)
        stems.append({"name": name, "role": role, "path": None, "mode": "mono" if role == "bass" else "poly",
                      "transcription": {"backend": "stemforge.resynth/1 from %s" % src["name"], "skipped": False,
                                        "reason": None, "warnings": [], "source": "resynth", "stats": {}}})
        report[name] = {"from": src["name"], "hits_read": len(events), "notes": n_notes}
    for c in clips:                                    # keep every note inside its clip
        end = float(c["length_beats"])
        c["notes"] = sorted([{**n, "duration": round(min(n["duration"], end - n["start"]), 4)}
                             for n in c["notes"] if n["start"] < end - 1e-6 and end - n["start"] >= 0.04],
                            key=lambda n: (n["start"], n["pitch"]))
    out["stems"], out["clips"], out["placements"] = stems, clips, placements
    out["song"] = {**out["song"], "name": out["song"]["name"] + " (rebuilt)"}
    out["generation"] = {"method": "resynth/1", "swing_pct": swing, "octaves": octaves, "rules": RULES, "report": report,
                         "kept_transcribed": sorted(drum_names), "rebuilt": list(report)}
    return out


def check_against_audio(bp: dict, gen: dict) -> dict:
    """For every rebuilt layer: how well its hits line up with the hits found in the stem it came from.
    hit_match = F1 of onset agreement (tolerance 60 ms); found = share of the stem's hits present; false = share of the
    MIDI hits with no hit in the stem. Pitch is not re-scored here (the same tracker produced it)."""
    import librosa
    from .analyze.grid import BeatGrid
    from .verify import _onset_f1
    grid = BeatGrid(np.array(bp["global"]["beats_s"]))
    clips = {c["id"]: c for c in gen["clips"]}
    secs = {x["index"]: x for x in gen["sections"]}
    paths = {x["name"]: x.get("path") for x in bp["stems"]}
    out = {}
    for name, info in gen["generation"].get("report", {}).items():
        path = paths.get(info["from"])
        if not path:
            continue
        y, sr = librosa.load(path, sr=22050, mono=True)
        ref = librosa.onset.onset_detect(y=y, sr=sr, units="time", hop_length=512)
        starts = []
        for pl in gen["placements"]:
            if pl["stem"] != name:
                continue
            base = secs[pl["section"]]["start_bar"] * BEATS_PER_BAR
            starts += [base + n["start"] for n in clips[pl["clip"]]["notes"]]
        t = np.unique(np.round([float(grid.to_time(b)) for b in starts], 3))
        pr, rc, f1 = _onset_f1(ref, t)
        out[name] = {"hit_match": round(float(f1), 2), "found": round(float(rc), 2), "false": round(1.0 - float(pr), 2)}
    return out
