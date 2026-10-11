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
