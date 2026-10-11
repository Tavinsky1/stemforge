"""Native Stemforge window: 1 Stems -> 2 Analyze -> 3 Send to Ableton, with a live Ableton status pill."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QToolTip,
                               QVBoxLayout, QWidget)

from ..build.backends import NotSupported
from . import actions, live, theme


class Worker(QThread):
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.log.emit))
        except NotSupported as e:
            self.failed.emit(str(e))
        except (ConnectionRefusedError, TimeoutError, OSError) as e:
            self.failed.emit("Cannot reach Ableton (%s). Open Live 12 with AbletonMCP selected as a Control Surface, "
                             "or export .mid files instead." % e)
        except Exception as e:  # shown to the user, never silent
            self.failed.emit("%s: %s" % (type(e).__name__, e))


class Probe(QThread):
    result = Signal(dict)

    def __init__(self, known=None):
        super().__init__()
        self.known = known

    def run(self):
        self.result.emit(live.probe(known=self.known))


def card(title: str, step: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(); f.setObjectName("card")
    lay = QVBoxLayout(f); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(12)
    head = QHBoxLayout(); n = QLabel(step); n.setObjectName("step")
    t = QLabel(title); t.setObjectName("h2")
    head.addWidget(n); head.addWidget(t); head.addStretch()
    lay.addLayout(head)
    return f, lay


class DropArea(QFrame):
    folderChosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop"); self.setAcceptDrops(True); self.setProperty("hover", False)
        self.setMinimumHeight(86); self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        self.title = QLabel("Drop a folder of stems here"); self.title.setObjectName("h2"); self.title.setAlignment(Qt.AlignCenter)
        self.sub = QLabel("or click to choose  ·  WAV, MP3, FLAC, AIFF  ·  one file per stem"); self.sub.setObjectName("muted")
        self.sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.title); lay.addWidget(self.sub)

    def _hover(self, on):
        self.setProperty("hover", on); self.style().unpolish(self); self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction(); self._hover(True)

    def dragLeaveEvent(self, e):
        self._hover(False)

    def dropEvent(self, e):
        self._hover(False)
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            self.folderChosen.emit(str(p if p.is_dir() else p.parent)); return

    def mousePressEvent(self, e):
        d = QFileDialog.getExistingDirectory(self, "Choose the folder with the stems")
        if d:
            self.folderChosen.emit(d)


class Timeline(QWidget):
    """Colour bar of the detected sections; hover shows why a boundary was placed."""

    def __init__(self):
        super().__init__()
        self.sections, self.n_bars = [], 1
        self.setMinimumHeight(70); self.setMouseTracking(True)

    def set_sections(self, sections, n_bars):
        self.sections, self.n_bars = sections, max(n_bars, 1); self.update()

    def _rects(self):
        w = self.width(); out = []
        for s in self.sections:
            x = s["start_bar"] / self.n_bars * w; ww = s["length_bars"] / self.n_bars * w
            out.append((QRectF(x + 1, 6, max(ww - 2, 2), 40), s))
        return out

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font()); f.setPixelSize(11); p.setFont(f)
        for r, s in self._rects():
            p.setBrush(QColor(theme.SECTION_COLORS.get(s["label"], "#555"))); p.setPen(Qt.NoPen); p.drawRoundedRect(r, 5, 5)
            if r.width() > 54:
                p.setPen(QColor("#fff")); p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                                                     "%s" % s["label"].capitalize())
            p.setPen(QColor(theme.MUTED)); p.drawText(QPointF(r.x() + 2, 62), "bar %d" % (s["start_bar"] + 1)) if r.width() > 50 else None

    def mouseMoveEvent(self, e):
        for r, s in self._rects():
            if r.contains(e.position()):
                ev = [("%s %s" % (x["stem"], x["event"])) for x in s["evidence"] if "stem" in x] or ["start of the song"]
                QToolTip.showText(e.globalPosition().toPoint(),
                                  "%s · %d bars\n%s" % (s["name"], s["length_bars"], "\n".join(ev)), self); return


def pill_style(color: str) -> str:
    return "QPushButton{background:%s22;color:%s;border:1px solid %s66;border-radius:11px;padding:3px 10px;}" % (color, color, color)


def fit_rows(table: QTableWidget, n: int, row_h: int = 34) -> None:
    """Show every row: the page scrolls, the table does not (nested scrollbars hid rows)."""
    h = row_h * (n + 1) + 2
    table.setMinimumHeight(h); table.setMaximumHeight(h)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stemforge"); self.resize(1000, 820)
        self.folder = None; self.stems = []; self.bp = None; self.report = None; self.worker = None; self.live = {}
        root = QWidget(); root.setObjectName("root"); self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea(); sc.setWidgetResizable(True); outer.addWidget(sc)
        body = QWidget(); body.setObjectName("root"); sc.setWidget(body)
        col = QVBoxLayout(body); col.setContentsMargins(24, 20, 24, 20); col.setSpacing(16)

        head = QHBoxLayout()
        t = QLabel("Stemforge"); t.setObjectName("h1")
        sub = QLabel("Rebuild a song from its stems as MIDI in Ableton Live"); sub.setObjectName("muted")
        tl = QVBoxLayout(); tl.setSpacing(0); tl.addWidget(t); tl.addWidget(sub)
        head.addLayout(tl); head.addStretch()
        # Live is only contacted after the user clicks this: opening the app never touches an open set.
        self.pill = QPushButton("Connect to Ableton"); self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setStyleSheet(pill_style(theme.MUTED)); self.pill.clicked.connect(self.connect_live)
        self.pill.setToolTip("Checks that Ableton is reachable. Read-only: nothing in your set is changed.")
        head.addWidget(self.pill)
        col.addLayout(head)

        # 1 stems
        c1, l1 = card("Stems", "1"); col.addWidget(c1)
        self.drop = DropArea(); self.drop.folderChosen.connect(self.load_folder); l1.addWidget(self.drop)
        self.stem_table = QTableWidget(0, 4); self.stem_table.setHorizontalHeaderLabels(["Use", "Stem", "What it is", "File"])
        self.stem_table.verticalHeader().setVisible(False); self.stem_table.setShowGrid(False)
        h = self.stem_table.horizontalHeader(); h.setSectionResizeMode(1, QHeaderView.Stretch); h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.stem_table.setColumnWidth(0, 44); self.stem_table.setColumnWidth(2, 130); self.stem_table.setMaximumHeight(0)
        self.stem_table.setSelectionMode(QTableWidget.NoSelection)
        l1.addWidget(self.stem_table)

        # 2 analyze
        c2, l2 = card("Analyze", "2"); col.addWidget(c2)
        r = QHBoxLayout()
        self.btn_an = QPushButton("Analyze song"); self.btn_an.setObjectName("primary"); self.btn_an.setEnabled(False)
        self.btn_an.clicked.connect(self.analyze)
        self.facts = QLabel("Choose a folder first."); self.facts.setObjectName("muted")
        r.addWidget(self.btn_an); r.addWidget(self.facts, 1); l2.addLayout(r)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.hide(); l2.addWidget(self.progress)
        self.timeline = Timeline(); self.timeline.hide(); l2.addWidget(self.timeline)
        self.warn_label = QLabel(""); self.warn_label.setWordWrap(True); self.warn_label.setTextFormat(Qt.RichText)
        self.warn_label.hide(); l2.addWidget(self.warn_label)
        self.res_table = QTableWidget(0, 4); self.res_table.setHorizontalHeaderLabels(["Stem", "Notes", "Result", "Detail"])
        self.res_table.verticalHeader().setVisible(False); self.res_table.setShowGrid(False)
        h = self.res_table.horizontalHeader(); h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.res_table.setColumnWidth(0, 160); self.res_table.setColumnWidth(1, 60); self.res_table.setColumnWidth(2, 110)
        self.res_table.setMaximumHeight(0); self.res_table.setSelectionMode(QTableWidget.NoSelection)
        l2.addWidget(self.res_table)

        # 3 send
        c3, l3 = card("Send to Ableton", "3"); col.addWidget(c3)
        mr = QHBoxLayout(); mr.addWidget(QLabel("Layout"))
        self.rb_sess = QRadioButton("Session  ·  one scene per section"); self.rb_arr = QRadioButton("Arrangement  ·  clips on the timeline")
        self.rb_sess.setChecked(True); g = QButtonGroup(self); g.addButton(self.rb_sess); g.addButton(self.rb_arr)
        mr.addWidget(self.rb_sess); mr.addWidget(self.rb_arr); mr.addStretch(); l3.addLayout(mr)
        self.cb_tempo = QCheckBox("Also change Live's tempo to the song's tempo"); l3.addWidget(self.cb_tempo)
        self.safety = QLabel("Only adds new tracks and scenes. Nothing you already have in the set is changed or deleted. "
                             "Live's tempo is left alone unless you tick the box.")
        self.safety.setObjectName("muted"); self.safety.setWordWrap(True); l3.addWidget(self.safety)
        br = QHBoxLayout()
        self.btn_live = QPushButton("Build in Ableton"); self.btn_live.setObjectName("primary")
        self.btn_prev = QPushButton("Preview (changes nothing)"); self.btn_mid = QPushButton("Export .mid files")
        for b in (self.btn_live, self.btn_prev, self.btn_mid):
            b.setEnabled(False); br.addWidget(b)
        br.addStretch(); l3.addLayout(br)
        self.btn_live.clicked.connect(lambda: self.build("live")); self.btn_prev.clicked.connect(lambda: self.build("preview"))
        self.btn_mid.clicked.connect(lambda: self.build("midi"))
        self.outcome = QLabel(""); self.outcome.setWordWrap(True); self.outcome.setTextFormat(Qt.RichText)
        self.outcome.setMinimumHeight(56); self.outcome.setAlignment(Qt.AlignTop | Qt.AlignLeft); l3.addWidget(self.outcome)

        # log
        self.log_toggle = QPushButton("Show details"); self.log_toggle.clicked.connect(self.toggle_log)
        col.addWidget(self.log_toggle, 0, Qt.AlignLeft)
        self.logbox = QPlainTextEdit(); self.logbox.setReadOnly(True); self.logbox.setMaximumHeight(180); self.logbox.hide()
        col.addWidget(self.logbox); col.addStretch()

        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_live)   # started by connect_live()

    # ---- helpers
    def log(self, s):
        self.logbox.appendPlainText(s)

    def toggle_log(self):
        v = not self.logbox.isVisible(); self.logbox.setVisible(v); self.log_toggle.setText("Hide details" if v else "Show details")

    def run(self, fn, done, failed=None):
        self.worker = Worker(fn); self.worker.log.connect(self.log); self.worker.done.connect(done)
        self.worker.failed.connect(failed or self.show_error); self.worker.start()

    def show_error(self, msg):
        self.progress.hide(); self.outcome.setText("<span style='color:%s'>%s</span>" % (theme.BAD, msg))
        self.facts.setText(msg) if self.btn_an.isEnabled() is False else None
        self.btn_an.setEnabled(self.folder is not None); self.log("ERROR: " + msg)

    # ---- ableton status
    def connect_live(self):
        self.pill.setText("Checking Ableton…")
        self.refresh_live(force=True)
        self.timer.start(10000)           # slow poll so the pill follows Live opening/closing

    def refresh_live(self, force=False):
        if getattr(self, "_probe", None) and self._probe.isRunning():
            return
        if not force and self.worker is not None and self.worker.isRunning():
            return                         # never compete with a build for Live's attention
        self._probe = Probe(known=self.live); self._probe.result.connect(self.on_live); self._probe.start()

    def on_live(self, r):
        self.live = r
        color = theme.OK if r["connected"] else theme.WARN
        self.pill.setText("●  " + r["message"]); self.pill.setStyleSheet(pill_style(color))
        self.update_buttons()

    # ---- step 1
    def load_folder(self, folder):
        try:
            stems = actions.stems_from_folder(folder)
        except Exception as e:
            self.show_error("Cannot read that folder: %s" % e); return
        if not stems:
            self.show_error("No audio files found in that folder."); return
        self.folder, self.stems, self.bp, self.report = folder, stems, None, None
        self.drop.title.setText(Path(folder).name); self.drop.sub.setText("%d stems found  ·  click to choose another folder" % len(stems))
        t = self.stem_table; t.setRowCount(len(stems))
        for i, s in enumerate(stems):
            cb = QCheckBox(); cb.setChecked(s.mode != "skip"); w = QWidget(); hl = QHBoxLayout(w); hl.addWidget(cb)
            hl.setAlignment(Qt.AlignCenter); hl.setContentsMargins(0, 0, 0, 0); t.setCellWidget(i, 0, w)
            t.setItem(i, 1, QTableWidgetItem(s.name))
            combo = QComboBox(); combo.addItems(actions.ROLES); combo.setCurrentText(s.role); t.setCellWidget(i, 2, combo)
            t.setItem(i, 3, QTableWidgetItem(Path(s.path).name)); t.item(i, 3).setForeground(QColor(theme.MUTED))
            t.setRowHeight(i, 34)
        fit_rows(t, len(stems))
        self.facts.setText("Check that each stem is labelled correctly, then analyze."); self.btn_an.setEnabled(True)
        self.res_table.setMaximumHeight(0); self.res_table.setMinimumHeight(0)
        self.timeline.hide(); self.warn_label.hide(); self.outcome.setText(""); self.update_buttons()

    def chosen_stems(self):
        out = []
        for i, s in enumerate(self.stems):
            if self.stem_table.cellWidget(i, 0).findChild(QCheckBox).isChecked():
                out.append(actions.make_stem(s, self.stem_table.cellWidget(i, 2).currentText()))
        return out

    # ---- step 2
    def analyze(self):
        stems = self.chosen_stems()
        if not stems:
            self.show_error("Tick at least one stem."); return
        self.btn_an.setEnabled(False); self.progress.show(); self.facts.setText("Analyzing… this takes a minute or two for a full song.")
        self.outcome.setText(""); self.update_buttons()
        self.run(lambda log: actions.analyze_folder(self.folder, stems, log), self.analyzed)

    def analyzed(self, res):
        self.bp, rep = res; self.report = rep["stems"]; self.progress.hide(); self.btn_an.setEnabled(True)
        g = self.bp["global"]; key = g["key"]
        k = "%s %s" % (key["tonic"], key["mode"]) if key else "no key"
        self.facts.setText("%.1f BPM  ·  %s  ·  %d bars  ·  %d sections" % (g["tempo"], k, g["n_bars"], len(self.bp["sections"])))
        warn = list(self.bp.get("warnings", []))
        self.timeline.set_sections(self.bp["sections"], g["n_bars"]); self.timeline.show()
        rows = self.bp["stems"]; t = self.res_table; t.setRowCount(len(rows))
        for i, s in enumerate(rows):
            n = s["name"]; item = self.report.get(n, {"status": "no notes"})
            label, detail = actions.quality(item) if not s["transcription"].get("skipped") else ("out", s["transcription"]["reason"])
            col = {"ok": theme.OK, "check": theme.WARN, "out": theme.BAD}[label]
            txt = {"ok": "● Good", "check": "● Check by ear", "out": "● Left out"}[label]
            vals = [n, str(len(s["transcription"]["notes"])), txt, detail]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v); t.setItem(i, j, it)
                if j == 2:
                    it.setForeground(QColor(col))
                if j == 3:
                    it.setForeground(QColor(theme.MUTED))
            t.setRowHeight(i, 34)
        fit_rows(t, len(rows))
        if warn:   # its own label: a later build result must not overwrite these
            self.warn_label.setText("<span style='color:%s'>Heads up:<br>%s</span>"
                                    % (theme.WARN, "<br>".join("• " + x for x in warn)))
            self.warn_label.show()
        else:
            self.warn_label.hide()
        self.update_buttons()

    # ---- step 3
    def update_buttons(self):
        ready = self.bp is not None and self.report is not None
        self.btn_prev.setEnabled(ready); self.btn_mid.setEnabled(ready)
        arr_ok = self.live.get("connected") and self.live.get("arrangement")
        self.rb_arr.setToolTip("" if arr_ok else "Needs the updated Remote Script in Live (shown in the status pill).")
        self.btn_live.setEnabled(bool(ready and self.live.get("connected")))

    def build(self, target):
        if not self.bp:
            return
        mode = "arrangement" if self.rb_arr.isChecked() else "session"
        out_dir = str(Path(self.folder) / "stemforge_midi")
        for b in (self.btn_live, self.btn_prev, self.btn_mid):
            b.setEnabled(False)
        self.progress.show(); self.outcome.setText("Working…")
        self.run(lambda log: actions.run_build(self.bp, self.report, mode=mode, target=target, out_dir=out_dir,
                                               set_tempo=self.cb_tempo.isChecked(), include=set(), port=9877, log=log),
                 lambda s: self.built(s, target, out_dir))

    def built(self, s, target, out_dir):
        self.progress.hide(); self.update_buttons()
        left = "".join("<br>Left out: %s (%s)" % (n, r) for n, r in s["excluded"].items())
        if target == "preview":
            head = "Preview: would create %d tracks and %d clips (%d notes). Nothing was changed. See details." % (s["tracks"], s["clips"], s["notes"])
            self.logbox.show(); self.log_toggle.setText("Hide details")
        elif target == "midi":
            head = "Saved MIDI files to %s" % out_dir
        else:
            ok, total = s["readback"]
            color = theme.OK if ok == total else theme.BAD
            head = ("<span style='color:%s'>Built in Ableton: %d tracks, %d clips. Checked by reading the notes back from Live: "
                    "%d of %d clips match.</span>" % (color, s["tracks"], s["clips"], ok, total))
        self.outcome.setText(head + left)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.QSS)
    w = Window(); w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
