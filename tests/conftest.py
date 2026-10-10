"""Synthetic 'song' stems: 32 bars @124 BPM. Drums out in bars 16-24 (breakdown), bass enters at bar 8."""
import numpy as np
import pytest
import soundfile as sf

SR = 22050
BPM = 124.0


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def make_song(folder, bars=32, bpm=BPM):
    beat = 60.0 / bpm
    lead_in = 0.25
    n = int((bars * 4 * beat + lead_in) * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(1)
    kick = np.zeros(n); hat = np.zeros(n); bass = np.zeros(n); lead = np.zeros(n)
    truth = {"bass": [], "kick": []}
    for bar in range(bars):
        drums_on = not (16 <= bar < 24)
        for b in range(4):
            t0 = (bar * 4 + b) * beat + lead_in
            a = int(t0 * SR)
            if drums_on:
                m = int(0.15 * SR); tt = np.arange(m) / SR
                kick[a:a + m] += np.sin(2 * np.pi * (50 + 100 * np.exp(-tt * 40)) * tt) * np.exp(-tt * 18)
                truth["kick"].append(t0)
                h = int((t0 + beat / 2) * SR); hm = int(0.04 * SR)
                if h + hm < n:
                    hat[h:h + hm] += rng.standard_normal(hm) * np.linspace(1, 0, hm) * 0.4
            if bar >= 8:
                note = [38, 38, 41, 36][b]
                s = int(t0 * SR); e = int((t0 + beat * 0.9) * SR)
                tt = np.arange(e - s) / SR
                bass[s:e] += 0.5 * np.sin(2 * np.pi * midi_hz(note) * tt) * np.minimum(1, tt * 100)
                truth["bass"].append((note, t0))
            if bar >= 12 and b % 2 == 0:
                note = [62, 65][(b // 2) % 2]
                s = int(t0 * SR); e = int((t0 + beat * 1.8) * SR)
                tt = np.arange(e - s) / SR
                lead[s:e] += 0.3 * np.sin(2 * np.pi * midi_hz(note) * tt) * np.minimum(1, tt * 100) * np.exp(-tt * 1.5)
    # pad every stem to the same length with a short tail
    for name, y in (("drums_kick", kick), ("hats", hat), ("bass", bass), ("synth_lead", lead)):
        sf.write(str(folder / (name + ".wav")), y.astype(np.float32), SR)
    return truth


@pytest.fixture(scope="session")
def song(tmp_path_factory):
    d = tmp_path_factory.mktemp("song")
    truth = make_song(d)
    return d, truth
