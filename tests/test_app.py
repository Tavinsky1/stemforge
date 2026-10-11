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
