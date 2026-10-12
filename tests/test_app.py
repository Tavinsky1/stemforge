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


def test_idea_and_compose_flow_in_the_window(qapp, song):
    from stemforge.app.window import Window
    folder, _ = song
    w = Window()
    w.show()
    w.load_folder(str(folder))
    assert not w.btn_idea.isEnabled() and not w.btn_compose.isEnabled() and not w.rb_src_gen.isEnabled()
    w.analyze()
    pump(qapp, lambda: w.bp is not None and not w.busy)
    assert w.btn_idea.isEnabled() and not w.btn_compose.isEnabled()       # idea first
    w.read_idea()
    assert not w.btn_idea.isEnabled() and not w.btn_prev.isEnabled()        # one job at a time
    pump(qapp, lambda: w.idea is not None and not w.busy)
    assert (folder / (folder.name + ".idea.json")).exists() or list(folder.glob("*.idea.json"))
    assert "drone" in w.idea_view.text() or "Key" in w.idea_view.text()
    assert w.btn_compose.isEnabled() and not w.btn_take.isEnabled()
    w.compose_parts()
    pump(qapp, lambda: w.gen_bp is not None and not w.busy)
    assert w.rb_src_gen.isChecked() and w.btn_take.isEnabled()
    assert any(c["stem"] == "G Keys" for c in w.gen_bp["clips"]) or any(c["stem"] == "G Synth" for c in w.gen_bp["clips"])
    assert "outside the song's palette" in w.compose_view.text()
    first_seed_clips = [c["notes"] for c in w.gen_bp["clips"] if c["stem"].startswith("G ")]
    # preview and MIDI export build the COMPOSED version
    w.build("preview")
    pump(qapp, lambda: "Preview of the composed version" in w.outcome.text())
    w.build("midi")
    pump(qapp, lambda: "Saved MIDI files of the composed version" in w.outcome.text())
    assert list((folder / "stemforge_generated").glob("*.mid"))
    # another take changes the music, the same take does not
    w.another_take()
    pump(qapp, lambda: not w.busy and w.seed.value() == 1 and "Take 1" in w.compose_view.text())
    assert [c["notes"] for c in w.gen_bp["clips"] if c["stem"].startswith("G ")] != first_seed_clips
    # switching back builds the plain transcription
    w.rb_src_tr.setChecked(True)
    w.build("preview")
    pump(qapp, lambda: "Preview of the transcription" in w.outcome.text())
    # a new analysis clears what was composed from the old one
    w.reset_compose()
    assert w.gen_bp is None and not w.rb_src_gen.isEnabled()
    w.timer.stop()


def test_compose_buttons_stay_disabled_while_a_job_runs(qapp):
    from stemforge.app.window import Window
    w = Window()
    w.bp, w.report, w.idea, w.gen_bp = {"x": 1}, {}, {"y": 1}, {"z": 1}
    w.busy = False
    w.update_buttons()
    assert w.btn_idea.isEnabled() and w.btn_compose.isEnabled() and w.btn_take.isEnabled()
    w.busy = True
    w.update_buttons()
    assert not (w.btn_idea.isEnabled() or w.btn_compose.isEnabled() or w.btn_take.isEnabled() or w.btn_prev.isEnabled())
    w.timer.stop()


def test_rules_are_shown_in_the_window(qapp):
    from stemforge import compose
    from stemforge.app.window import Window
    w = Window()
    w.show_rules()
    text = w.logbox.toPlainText()
    assert all(r in text for r in compose.RULES[:3])
    w.timer.stop()
