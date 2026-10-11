"""Import a MIDI file as the transcription of one stem (e.g. exported from NeuralNote, a DAW, or hand-edited).

By default note times are taken in SECONDS from the stem's start (through the file's tempo map) and mapped onto
the blueprint's beat grid. That is right for a MIDI exported from the stem file itself, whatever tempo the file
claims. Pass as_beats=True when the MIDI's bar/beat positions already line up with the song's bar 1.
"""
from __future__ import annotations

import mido

from .analyze import clips as clipmod, quantize as qmod
from .analyze.grid import BeatGrid
import numpy as np


def read_notes(path: str, as_beats: bool = False) -> tuple[list[dict], float | None, int]:
    """Returns (notes, first_tempo_bpm, unclosed_note_count). Notes carry start_s/end_s, or start/duration for as_beats."""
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat
    tempo, ticks, sec = 500000, 0, 0.0
    first_bpm = None
    open_: dict = {}
    notes: list[dict] = []
    for msg in mido.merge_tracks(mid.tracks):
        ticks += msg.time
        sec += msg.time * tempo / (tpb * 1e6)
        if msg.type == "set_tempo":
            tempo = msg.tempo
            if first_bpm is None:
                first_bpm = mido.tempo2bpm(tempo)
        elif msg.type == "note_on" and msg.velocity > 0:
            open_.setdefault((msg.channel, msg.note), []).append((sec, ticks / tpb, msg.velocity))
        elif msg.type in ("note_off", "note_on"):
            stack = open_.get((msg.channel, msg.note))
            if stack:
                s_sec, s_beat, vel = stack.pop(0)
                if as_beats:
                    notes.append({"pitch": msg.note, "start": s_beat, "duration": ticks / tpb - s_beat, "velocity": vel})
                else:
                    notes.append({"pitch": msg.note, "start_s": s_sec, "end_s": sec, "velocity": vel})
    unclosed = sum(len(v) for v in open_.values())
    return notes, first_bpm, unclosed


def import_into_blueprint(bp: dict, stem_name: str, path: str, as_beats: bool = False,
                          min_confidence: float = 0.0, log=print) -> dict:
    stem = next((s for s in bp["stems"] if s["name"] == stem_name), None)
    if stem is None:
        raise ValueError("no stem named %r; stems are: %s" % (stem_name, ", ".join(s["name"] for s in bp["stems"])))
    raw, file_bpm, unclosed = read_notes(path, as_beats)
    if not raw:
        raise ValueError("no notes found in %s" % path)
    warnings = []
    song_bpm = bp["global"]["tempo"]
    if file_bpm and abs(file_bpm - song_bpm) > 0.5:
        warnings.append("MIDI tempo is %.2f BPM, the song is %.2f BPM; %s" % (
            file_bpm, song_bpm, "bar/beat positions used as-is" if as_beats else "positions converted by time, not by beats"))
    if unclosed:
        warnings.append("%d notes had no note-off and were ignored" % unclosed)

    if as_beats:
        beats = [{**n, "confidence": 1.0} for n in raw]
    else:
        grid = BeatGrid(np.array(bp["global"]["beats_s"]))
        beats = qmod.to_beats([{**n, "confidence": 1.0} for n in raw], grid)
    q = bp["global"]["quantize"]
    drums = stem["mode"] == "drums"
    cleaned, stats = qmod.quantize(beats, q["resolution_beats"], q["strength"], drums=drums, mono=(stem["mode"] == "mono"))
    if stats.get("dropped_negative"):
        warnings.append("%d notes before the first downbeat were dropped (pickup)" % stats["dropped_negative"])
    notes = [{"pitch": n["pitch"], "start": n["start"], "duration": n["duration"],
              "velocity": max(1, min(127, int(n["velocity"]))), "confidence": 1.0, "source": "imported"}
             for n in cleaned]
    tr = stem["transcription"]
    tr.update(backend="imported:%s" % path.split("/")[-1], skipped=False, reason=None,
              warnings=warnings, notes=notes, stats=stats)
    clipmod.derive_clips(bp, min_confidence)
    for w in warnings:
        log("WARNING: " + w)
    return {"stem": stem_name, "notes": len(notes), "clips": len(bp["clips"])}
