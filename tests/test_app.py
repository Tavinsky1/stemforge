"""Offscreen smoke test of the native window (no display needed)."""
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from stemforge.app import actions, live  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(app, cond, timeout=240):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.05)
    assert cond(), "timed out"


def test_probe_when_live_is_not_running():
    r = live.probe(port=1, timeout=0.2)
    assert r["connected"] is False and "Ableton" in r["message"]


def test_window_flow(qapp, song):
    from stemforge.app.window import Window
    folder, _ = song
    w = Window()
    w.show()
    w.load_folder(str(folder))
    assert w.stem_table.rowCount() == 4 and w.btn_an.isEnabled()
    assert not w.btn_live.isEnabled()                      # nothing to send yet
    w.analyze()
    pump(qapp, lambda: w.bp is not None)
    assert w.res_table.rowCount() == 4 and "BPM" in w.facts.text()
    w.build("preview")
    pump(qapp, lambda: "Preview" in w.outcome.text())
    assert "Nothing was changed" in w.outcome.text()
    w.build("midi")
    pump(qapp, lambda: "Saved MIDI" in w.outcome.text())
    assert list((folder / "stemforge_midi").glob("*.mid"))
    w.timer.stop()


def test_opening_the_app_never_contacts_live(qapp, monkeypatch):
    from stemforge.app.window import Window
    called = []
    monkeypatch.setattr(live, "probe", lambda *a, **k: called.append(1) or {"connected": False, "message": "x"})
    w = Window()
    w.show()
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.02)
    assert not called and not w.timer.isActive()
    w.connect_live()                               # only an explicit click probes
    pump(qapp, lambda: called)
    assert w.timer.isActive()
    w.timer.stop()


def test_warnings_survive_a_build(qapp, song):
    from stemforge.app.window import Window
    folder, _ = song
    w = Window()
    w.load_folder(str(folder))
    w.analyze()
    pump(qapp, lambda: w.bp is not None)
    shown = w.warn_label.text()
    w.build("preview")
    pump(qapp, lambda: "Preview" in w.outcome.text())
    assert w.warn_label.text() == shown            # not overwritten by the build result
    assert w.res_table.maximumHeight() >= 34 * w.res_table.rowCount()   # every row visible
    w.timer.stop()


def test_live_button_needs_a_connection(qapp, song):
    from stemforge.app.window import Window
    w = Window()
    w.bp, w.report = {"x": 1}, {}
    w.on_live({"connected": False, "arrangement": False, "message": "Ableton not found"})
    assert not w.btn_live.isEnabled()
    w.on_live({"connected": True, "arrangement": False, "message": "Ableton connected"})
    assert w.btn_live.isEnabled()
    w.timer.stop()


def test_select_stems_leaves_out_failures():
    bp = {"stems": [{"name": "a", "transcription": {"skipped": False}}, {"name": "b", "transcription": {"skipped": True, "reason": "silent"}}]}
    rep = {"a": {"onset_precision": 0.9, "coverage": 0.9}}
    keep, out = actions.select_stems(bp, rep, set())
    assert keep == ["a"] and out == {"b": "silent"}


def test_left_out_stem_can_be_forced_in(qapp, song):
    from PySide6.QtWidgets import QCheckBox
    from stemforge.analyze.pipeline import analyze
    from stemforge.app.window import Window
    folder, _ = song
    bp = analyze(str(folder), log=lambda *_: None)
    names = [s["name"] for s in bp["stems"]]
    good = {"onset_precision": 0.9, "onset_recall": 0.9, "onset_f1": 0.9, "coverage": 0.9, "verdict": ["no objective problem found"]}
    rep = {n: dict(good) for n in names}
    rep[names[0]] = dict(good, onset_precision=0.01)          # clearly failed -> left out, but it has notes
    w = Window()
    w.folder = str(folder)
    w.analyzed((bp, {"stems": rep}))
    assert w.res_table.cellWidget(0, 4) is not None and w.forced_stems() == set()
    w.res_table.cellWidget(0, 4).findChild(QCheckBox).setChecked(True)
    assert w.forced_stems() == {names[0]}
    from stemforge import workflow
    keep, out = workflow.select_stems(bp, rep, include=w.forced_stems())
    assert names[0] in keep and not out
    w.timer.stop()


def test_plain_errors_are_plain():
    assert "Reinstall" in actions.plain_error(ImportError("x", name="basic_pitch"))
    assert "Connect to Ableton" in actions.plain_error(ConnectionRefusedError())
    assert "No audio files" in actions.plain_error(RuntimeError("no audio files found in /x"))
    msg = actions.plain_error(KeyError("zzz"))
    assert "Show details" in msg and "Traceback" not in msg


def test_clean_rebuild_flow_in_the_window(qapp, song):
    from stemforge.app.window import Window
    folder, _ = song
    w = Window()
    w.show()
    w.load_folder(str(folder))
    assert not w.btn_compose.isEnabled() and not w.rb_src_gen.isEnabled()
    w.analyze()
    pump(qapp, lambda: w.bp is not None and not w.busy)
    assert w.btn_compose.isEnabled()
    w.compose_parts()
    assert not w.btn_compose.isEnabled() and not w.btn_prev.isEnabled()      # one job at a time
    pump(qapp, lambda: w.gen_bp is not None and not w.busy)
    assert list(folder.glob("*.idea.json")) and list(folder.glob("*.rebuilt.blueprint.json"))
    assert w.rb_src_gen.isChecked() and "Rebuilt from the audio" in w.compose_view.text()
    assert "Matches the stem's own hits" in w.compose_view.text()
    names = {c["stem"] for c in w.gen_bp["clips"]}
    assert names & {"R Bass", "R Keys", "R Synth"}
    first = [c["notes"] for c in w.gen_bp["clips"] if c["stem"].startswith("R ")]
    # preview and MIDI export build the REBUILT version
    w.build("preview")
    pump(qapp, lambda: "Preview of the rebuilt version" in w.outcome.text())
    w.build("midi")
    pump(qapp, lambda: "Saved MIDI files of the rebuilt version" in w.outcome.text())
    assert list((folder / "stemforge_rebuilt").glob("*.mid"))
    # the same stems give the same MIDI again (deterministic; the second run uses the saved reading)
    w.compose_parts()
    pump(qapp, lambda: not w.busy and w.gen_bp is not None and "Rebuilt from the audio" in w.compose_view.text())
    assert [c["notes"] for c in w.gen_bp["clips"] if c["stem"].startswith("R ")] == first
    # switching back builds the plain transcription
    w.rb_src_tr.setChecked(True)
    w.build("preview")
    pump(qapp, lambda: "Preview of the transcription" in w.outcome.text())
    w.reset_compose()
    assert w.gen_bp is None and not w.rb_src_gen.isEnabled()
    w.timer.stop()


def test_octave_choice_shifts_a_layer(qapp, song):
    from stemforge.app.window import Window
    folder, _ = song
    w = Window()
    w.load_folder(str(folder))
    w.analyze()
    pump(qapp, lambda: w.bp is not None and not w.busy)
    w.compose_parts()
    pump(qapp, lambda: w.gen_bp is not None and not w.busy)
    base = {r: [n["pitch"] for c in w.gen_bp["clips"] if c["stem"] == r for n in c["notes"]] for r in ("R Bass", "R Synth")}
    idx = w.octaves["synth"].findData(1)
    w.octaves["synth"].setCurrentIndex(idx)
    w.gen_bp = None
    w.compose_parts()
    pump(qapp, lambda: w.gen_bp is not None and not w.busy)
    shifted = [n["pitch"] for c in w.gen_bp["clips"] if c["stem"] == "R Synth" for n in c["notes"]]
    if base["R Synth"]:
        assert shifted == [p + 12 for p in base["R Synth"]]
    w.timer.stop()


def test_rebuild_button_waits_for_a_job(qapp):
    from stemforge.app.window import Window
    w = Window()
    w.bp, w.report = {"x": 1}, {}
    w.busy = False
    w.update_buttons()
    assert w.btn_compose.isEnabled()
    w.busy = True
    w.update_buttons()
    assert not (w.btn_compose.isEnabled() or w.btn_prev.isEnabled())
    w.timer.stop()


def test_how_it_works_is_shown_in_the_window(qapp):
    from stemforge import resynth
    from stemforge.app.window import Window
    w = Window()
    w.show_rules()
    text = w.logbox.toPlainText()
    assert all(r in text for r in resynth.RULES)
    w.timer.stop()


def test_start_from_zero_flow_needs_no_stems(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from stemforge.app.window import Window
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))       # never write into the real Documents
    w = Window()
    w.show()
    assert not w.rb_src_new.isEnabled() and not w.btn_prev.isEnabled()
    w.pick_style("house")
    assert w.key_box.currentData() is None and w.bpm_box.value() == 0          # Auto: every new song differs
    w.create_new()
    assert w.new_bp is not None and w.rb_src_new.isChecked() and w.rb_src_new.isEnabled()
    assert w.btn_prev.isEnabled() and w.btn_mid.isEnabled()                     # no analysis was needed
    assert "NotebookLM" in w.new_view.text() or "published recipe" in w.new_view.text()
    assert (Path(w.new_dir) / "song.created.blueprint.json").exists()
    assert "seed%d" % w.new_bp["generation"]["seed"] in w.new_dir and w.seed_box.value() == w.new_bp["generation"]["seed"]
    w.build("preview")
    pump(qapp, lambda: "Preview of the song created from zero" in w.outcome.text())
    w.build("midi")
    pump(qapp, lambda: "Saved MIDI files of the song created from zero" in w.outcome.text())
    assert list((Path(w.new_dir) / "midi").glob("*.mid"))
    w.timer.stop()


def test_every_press_of_new_song_is_a_different_song_and_keep_seed_recreates_it(qapp, tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from stemforge.app.window import Window
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    w = Window()
    w.pick_style("techno")
    songs, seeds = [], []
    for _ in range(5):
        w.create_new()
        songs.append(json.dumps(w.new_bp["clips"], sort_keys=True))
        seeds.append(w.new_bp["generation"]["seed"])
    assert len(set(songs)) == 5 and len(set(seeds)) == 5                          # five presses, five songs
    w.cb_keep_seed.setChecked(True)                                             # the seed of the last song is still in the box
    w.create_new()
    assert json.dumps(w.new_bp["clips"], sort_keys=True) == songs[-1]            # kept seed + same Auto choices -> same song
    w.timer.stop()


def test_out_of_range_tempo_is_shown_not_hidden(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from stemforge.app.window import Window
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    w = Window()
    w.bpm_box.setValue(175)
    w.create_new()
    assert "outside the usual range" in w.new_view.text()
    w.timer.stop()


def test_all_four_styles_are_buttons_and_each_one_creates_its_own_song(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from stemforge.app.window import Window
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    w = Window()
    w.show()
    assert set(w.style_btns) == {"techno", "house", "downtempo", "electro_cumbia"}
    assert all(b.isCheckable() and b.isVisible() for b in w.style_btns.values())
    assert w.current_style() == "techno"                       # one is always chosen
    seen = {}
    for key in ("house", "downtempo", "electro_cumbia", "techno"):
        w.style_btns[key].click()
        assert w.current_style() == key and sum(b.isChecked() for b in w.style_btns.values()) == 1
        w.create_new()
        seen[key] = w.new_bp["generation"]["style"]
        info = w.styles_mod.style_info(key)
        assert info["bpm"]["min"] <= w.new_bp["generation"]["bpm"] <= info["bpm"]["max"]
    assert seen == {k: k for k in seen}
    w.timer.stop()
