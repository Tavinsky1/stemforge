"""Native Stemforge window: 0 Start from zero | 1 Stems -> 2 Analyze -> 3 Clean rebuild -> 4 Send, with a live Ableton status pill."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QDoubleSpinBox, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QToolTip,
                               QVBoxLayout, QWidget)

from ..build.backends import DEFAULT_PORT, NotSupported
from . import actions, installer, live, theme


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
        except Exception as e:  # shown to the user in plain English; the technical detail goes to 'Show details'
            self.log.emit(traceback.format_exc())
            self.failed.emit(actions.plain_error(e))


class Probe(QThread):
    result = Signal(dict)

    def __init__(self, known=None):
        super().__init__()
        self.known = known

    def run(self):
        self.result.emit(live.probe(known=self.known))


def card(title: str, step: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(); f.setObjectName("card")
    f.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)   # extra window height goes below the cards, not into them
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
        self.idea = None; self.gen_bp = None; self.gen_report = None; self.busy = False
        self.new_bp = None; self.new_dir = None
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

        # 0 start from zero
        cN, lN = card("Start from zero  ·  no stems needed", "0"); col.addWidget(cN)
        from ..styles import create as styles_mod
        self.styles_mod = styles_mod
        nw = QLabel("Choose a style and Stemforge assembles a song skeleton: the style's own arrangement, drums, a bass with "
                    "the groove and note placement of that style, chords, pad and lead. Every pattern comes from your NotebookLM "
                    "research, from real loops measured on this Mac, or from published recipes, and the window shows which. "
                    "<b>Nothing is random</b>: the same choices always give the same MIDI.")
        nw.setObjectName("muted"); nw.setWordWrap(True); nw.setTextFormat(Qt.RichText); lN.addWidget(nw)
        # four styles as four clear buttons, each saying what it is
        sr_ = QHBoxLayout(); sr_.setSpacing(10)
        self.style_btns = {}
        self.style_group = QButtonGroup(self); self.style_group.setExclusive(True)
        blurbs = {"techno": "124-134 BPM · rolling bass", "house": "120-128 BPM · offbeat bass",
                  "downtempo": "80-100 BPM · broken beat", "electro_cumbia": "88-108 BPM · tumbao, guacharaca"}
        for key, label in (("techno", "Techno"), ("house", "House"), ("downtempo", "Downtempo"), ("electro_cumbia", "Electro cumbia")):
            b = QPushButton("%s\n%s" % (label, blurbs[key])); b.setCheckable(True); b.setObjectName("style")
            b.setMinimumHeight(54); b.setMinimumWidth(0); b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.style_btns[key] = b; self.style_group.addButton(b); sr_.addWidget(b, 1)
            b.clicked.connect(lambda _=False, k=key: self.pick_style(k))
        self.style_btns["techno"].setChecked(True)
        lN.addLayout(sr_)
        nr = QHBoxLayout()
        nr.addWidget(QLabel("Key"))
        self.key_box = QComboBox()
        for t in styles_mod.TONICS:
            self.key_box.addItem(t, t)
        nr.addWidget(self.key_box)
        nr.addWidget(QLabel("Tempo"))
        self.bpm_box = QDoubleSpinBox(); self.bpm_box.setRange(60, 180); self.bpm_box.setDecimals(0); self.bpm_box.setSuffix(" BPM")
        nr.addWidget(self.bpm_box)
        nr.addWidget(QLabel("Take"))
        self.new_take = QSpinBox(); self.new_take.setRange(0, 9)
        self.new_take.setToolTip("Another set of alternatives from the same library. Same number = same music.")
        nr.addWidget(self.new_take)
        self.cb_short = QCheckBox("Short (sections capped at 16 bars)"); nr.addWidget(self.cb_short)
        nr.addStretch(); lN.addLayout(nr)
        br0 = QHBoxLayout()
        self.btn_new = QPushButton("Create song"); self.btn_new.setObjectName("primary")
        self.btn_new.clicked.connect(self.create_new)
        self.new_status = QLabel("Pick a style, then press Create."); self.new_status.setObjectName("muted"); self.new_status.setWordWrap(True)
        br0.addWidget(self.btn_new); br0.addWidget(self.new_status, 1); lN.addLayout(br0)
        self.new_view = QLabel(""); self.new_view.setWordWrap(True); self.new_view.setTextFormat(Qt.RichText)
        self.new_view.hide(); lN.addWidget(self.new_view)
        self.style_changed()

        # 1 stems
        c1, l1 = card("Stems  ·  or start here to rebuild a song you have", "1"); col.addWidget(c1)
        self.hint = QLabel("<b>How to use</b><br>"
                           "1. Drop the folder that holds one audio file per stem (a song's stems from Suno, Demucs, etc.).<br>"
                           "2. Check each stem's label, then press <b>Analyze song</b> (a couple of minutes for a full track).<br>"
                           "3. <b>Preview</b> changes nothing. <b>Export .mid files</b> needs no Ableton. "
                           "To build inside Ableton, open a new, empty set and press <b>Connect to Ableton</b>.<br>"
                           "Stemforge only ever <i>adds</i> tracks and scenes; it never changes or deletes what is already in your set.")
        self.hint.setObjectName("muted"); self.hint.setWordWrap(True); self.hint.setTextFormat(Qt.RichText)
        l1.addWidget(self.hint)
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
        self.res_table = QTableWidget(0, 5); self.res_table.setHorizontalHeaderLabels(["Stem", "Notes", "Result", "Detail", "Build anyway"])
        self.res_table.verticalHeader().setVisible(False); self.res_table.setShowGrid(False)
        h = self.res_table.horizontalHeader(); h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.res_table.setColumnWidth(0, 160); self.res_table.setColumnWidth(1, 60); self.res_table.setColumnWidth(2, 110)
        self.res_table.setColumnWidth(4, 110)
        self.res_table.setMaximumHeight(0); self.res_table.setSelectionMode(QTableWidget.NoSelection)
        l2.addWidget(self.res_table)

        # 3 clean rebuild (optional)
        cI, lI = card("Clean rebuild  ·  Bass, Keys, Synth  ·  optional", "3"); col.addWidget(cI)
        why = QLabel("Dense synth parts transcribe badly. This reads <b>every hit straight from the stem's audio</b>: when it "
                     "hits (on the 16th grid, with the song's own swing), how hard, how long it rings, and the note the stem is "
                     "playing. Bars that repeat are cleaned into loops, so delay tails and noise disappear while fills stay. "
                     "<b>Nothing is random or invented</b>: the same stems always give the same MIDI. Drums and Percussion "
                     "stay as transcribed. The new tracks are named <b>R Bass</b>, <b>R Keys</b>, <b>R Synth</b>.")
        why.setObjectName("muted"); why.setWordWrap(True); why.setTextFormat(Qt.RichText); lI.addWidget(why)
        orow = QHBoxLayout()
        self.octaves = {}
        for role, label in (("bass", "Bass"), ("keys", "Keys"), ("synth", "Synth")):
            orow.addWidget(QLabel(label))
            cbx = QComboBox()
            for text, val in (("as in the song", 0), ("+1 octave", 1), ("+2 octaves", 2), ("-1 octave", -1)):
                cbx.addItem(text, val)
            cbx.setToolTip("Shift this layer by whole octaves if your sound needs a different register.")
            self.octaves[role] = cbx; orow.addWidget(cbx)
        self.cb_straight = QCheckBox("Straight 16ths (ignore the song's swing)"); orow.addWidget(self.cb_straight)
        orow.addStretch(); lI.addLayout(orow)
        ir = QHBoxLayout()
        self.btn_compose = QPushButton("Rebuild Bass, Keys && Synth from the audio"); self.btn_compose.setObjectName("primary")
        self.btn_compose.setEnabled(False); self.btn_compose.clicked.connect(lambda: self.compose_parts())
        self.btn_rules = QPushButton("Show how it works"); self.btn_rules.clicked.connect(self.show_rules)
        self.idea_status = QLabel("Analyze the song first."); self.idea_status.setObjectName("muted"); self.idea_status.setWordWrap(True)
        ir.addWidget(self.btn_compose); ir.addWidget(self.btn_rules); ir.addWidget(self.idea_status, 1); lI.addLayout(ir)
        self.idea_view = QLabel(""); self.idea_view.setWordWrap(True); self.idea_view.setTextFormat(Qt.RichText)
        self.idea_view.hide(); lI.addWidget(self.idea_view)
        self.compose_view = QLabel(""); self.compose_view.setWordWrap(True); self.compose_view.setTextFormat(Qt.RichText)
        self.compose_view.hide(); lI.addWidget(self.compose_view)

        # 4 send
        c3, l3 = card("Send to Ableton", "4"); col.addWidget(c3)
        sr0 = QHBoxLayout(); sr0.addWidget(QLabel("Build from"))
        self.rb_src_tr = QRadioButton("Transcription  ·  as analyzed"); self.rb_src_gen = QRadioButton("Rebuilt  ·  clean Bass, Keys && Synth")
        self.rb_src_new = QRadioButton("Created from zero"); self.rb_src_new.setEnabled(False)
        self.rb_src_tr.setChecked(True); self.rb_src_gen.setEnabled(False)
        gs = QButtonGroup(self); gs.addButton(self.rb_src_tr); gs.addButton(self.rb_src_gen); gs.addButton(self.rb_src_new)
        sr0.addWidget(self.rb_src_tr); sr0.addWidget(self.rb_src_gen); sr0.addWidget(self.rb_src_new); sr0.addStretch()
        l3.addLayout(sr0)
        self.rb_src_tr.toggled.connect(lambda _=None: self.update_buttons())
        self.rb_src_new.toggled.connect(lambda _=None: self.update_buttons())
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
        self.btn_install = QPushButton("Install Stemforge's Ableton script…")
        self.btn_install.setToolTip("Adds Stemforge's own, separate Control Surface script to the Remote Scripts folder "
                                    "of your Ableton User Library. Your other scripts are not touched. Does not contact Ableton.")
        self.btn_install.clicked.connect(self.install_script)
        self.script_note = QLabel(""); self.script_note.setObjectName("muted"); self.script_note.setWordWrap(True)
        sr = QHBoxLayout(); sr.addWidget(self.btn_install); sr.addWidget(self.script_note, 1); l3.addLayout(sr)
        self.refresh_script_note()
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
        """One background job at a time: every button that starts a job is disabled while one runs."""
        self.busy = True; self.update_buttons()

        def _done(r):
            self.busy = False
            done(r)
            self.update_buttons()

        def _failed(m):
            self.busy = False
            (failed or self.show_error)(m)
            self.update_buttons()
        self.worker = Worker(fn); self.worker.log.connect(self.log); self.worker.done.connect(_done)
        self.worker.failed.connect(_failed); self.worker.start()

    def show_error(self, msg):
        self.progress.hide(); self.outcome.setText("<span style='color:%s'>%s</span>" % (theme.BAD, msg))
        self.facts.setText(msg) if self.btn_an.isEnabled() is False else None
        self.btn_an.setEnabled(self.folder is not None); self.log("ERROR: " + msg)

    # ---- stemforge's ableton script (a separate control surface; other scripts are never touched)
    def refresh_script_note(self):
        try:
            ver = installer.source_version()
            pl = installer.plan()
        except Exception as e:
            self.script_note.setText(actions.plain_error(e)); return
        if pl is None:
            self.script_note.setText("Ableton's preferences folder was not found. Open Ableton Live once, then reopen Stemforge.")
            return
        word = {"current": "is installed and up to date", "different": "is installed but is a different version",
                "missing": "is not installed yet"}[pl["state"]]
        self.script_note.setText("Stemforge's Ableton script (%s) %s for %s. It is separate from your other scripts."
                                 % (ver, word, pl["live"]))

    def install_script(self):
        try:
            pl = installer.plan()
        except Exception as e:
            self.show_error(actions.plain_error(e)); return
        if pl is None:
            self.show_error("Could not find Ableton's preferences folder. Open Ableton Live once, then try again."); return
        if pl["state"] == "current":
            self.outcome.setText("Stemforge's script is already installed and up to date (%s)." % pl["version"]); return
        left = (", ".join(pl["left_alone"]) or "nothing else") if pl["left_alone"] else "no other scripts found"
        text = ("Stemforge adds its OWN script as a separate Control Surface.\n\n"
                "It will create exactly one file:\n%s\n\n"
                "Not touched: %s.\n" % (pl["target"], left))
        if pl["backup_to"]:
            text += "\nA different Stemforge script is already there; it is backed up first to ~/Documents/ableton-backups/.\n"
        text += "\nAbleton is not contacted and nothing is deleted."
        if QMessageBox.question(self, "Install Stemforge's Ableton script", text) != QMessageBox.Yes:
            return
        try:
            r = installer.install()
        except Exception as e:
            self.log(traceback.format_exc()); self.show_error(actions.plain_error(e)); return
        self.refresh_script_note()
        self.outcome.setText(
            "Installed Stemforge script %s for %s.%s<br><b>Now in Ableton:</b> Preferences &gt; Link, Tempo &amp; MIDI. "
            "In an <i>empty</i> Control Surface slot choose <b>Stemforge</b> (leave Input and Output as None). "
            "Leave your other slots as they are. If Stemforge is not in the list, restart Live. "
            "Then press <b>Connect to Ableton</b> here."
            % (r["version"], r["live"], ("<br>Backup of the previous Stemforge script: %s" % r["backup"]) if r["backup"] else ""))
        if r.get("unused_copy"):
            self.log("Note: an older Stemforge copy sits in %s. Live does not scan that folder on this setup; it can be "
                     "deleted by hand." % r["unused_copy"])

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
        msg = r["message"]
        try:
            want = installer.source_version()
        except Exception:
            want = None
        if r.get("connected") and r.get("version") and want and r["version"] != want:
            msg += " · script is %s, this app ships %s: reinstall it, then restart Live" % (r["version"], want)
            color = theme.WARN
        self.pill.setText("●  " + msg); self.pill.setStyleSheet(pill_style(color))
        self.pill.setToolTip(("Script loaded by Live: %s" % r["file"]) if r.get("file") else self.pill.toolTip())
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
        self.hint.hide()
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
        self.reset_compose()
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
            n_notes = len(s["transcription"]["notes"])
            if label == "out" and n_notes:     # force a left-out stem back in (the CLI's --include)
                cb = QCheckBox(); cb.setToolTip("Build this stem even though the check says it is unreliable")
                cell = QWidget(); hl = QHBoxLayout(cell); hl.addWidget(cb); hl.setAlignment(Qt.AlignCenter)
                hl.setContentsMargins(0, 0, 0, 0); t.setCellWidget(i, 4, cell)
            else:
                t.removeCellWidget(i, 4)
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

    # ---- step 0: start from zero
    def current_style(self) -> str:
        return next((k for k, b in self.style_btns.items() if b.isChecked()), "techno")

    def pick_style(self, key: str):
        self.style_btns[key].setChecked(True)
        self.style_changed()

    def style_changed(self):
        info = self.styles_mod.style_info(self.current_style())
        self.bpm_box.setValue(info["bpm"]["default"])
        self.key_box.setCurrentIndex(self.styles_mod.TONICS.index(info["tonic"]))

    def create_new(self):
        style, key = self.current_style(), self.key_box.currentData()
        try:
            bp = self.styles_mod.create(style, key, self.bpm_box.value(), take=self.new_take.value(), short=self.cb_short.isChecked())
        except Exception as e:
            self.show_error(actions.plain_error(e)); return
        self.new_bp = bp
        g = bp["generation"]
        out = Path.home() / "Documents" / "Stemforge" / "created" / ("%s-%s-%d-take%d" % (style, key.replace("#", "s"), round(g["bpm"]), g["take"]))
        out.mkdir(parents=True, exist_ok=True)
        from .. import blueprint
        blueprint.save(bp, str(out / "song.created.blueprint.json"))
        self.new_dir = str(out)
        lines = self.styles_mod.describe(bp)
        chk = g["checks"]
        facts = []
        if "bass_on_kick_steps_pct" in chk:
            facts.append("bass lands on the main kick steps in %.0f%% of its notes" % chk["bass_on_kick_steps_pct"])
        if "bass_on_offbeat_8ths_pct" in chk:
            facts.append("%.0f%% of bass notes sit on the offbeat 8ths" % chk["bass_on_offbeat_8ths_pct"])
        warn = "".join("<br><span style='color:%s'>%s</span>" % (theme.WARN, w) for w in bp["warnings"])
        self.new_view.setText("<b>%s</b>: %d bars, %d sections, swing %.0f%%.<br>%s<br><span style='color:%s'>Checks: %s.</span>%s"
                              "<br><span style='color:%s'>Saved in %s. Now choose <b>Created from zero</b> in step 4.</span>"
                              % (bp["song"]["name"], bp["global"]["n_bars"], len(bp["sections"]), g["swing_pct"],
                                 "<br>".join("• " + x for x in lines), theme.MUTED, "; ".join(facts) or "none", warn, theme.MUTED, self.new_dir))
        self.new_view.show()
        self.new_status.setText("Created. Preview, export or build it in step 4 (choose 'Created from zero').")
        self.rb_src_new.setEnabled(True); self.rb_src_new.setChecked(True)
        self.update_buttons()

    # ---- step 3: clean rebuild
    def reset_compose(self):
        self.idea = None; self.gen_bp = None; self.gen_report = None
        self.idea_view.hide(); self.compose_view.hide()
        self.rb_src_tr.setChecked(True); self.rb_src_gen.setEnabled(False)
        self.idea_status.setText("Ready: press the button (about 3 minutes the first time, seconds after that)."
                                 if self.bp is not None else "Analyze the song first.")

    def compose_parts(self):
        if self.bp is None or self.folder is None:
            return
        octaves = {r: cb.currentData() for r, cb in self.octaves.items()}
        straight = self.cb_straight.isChecked()
        self.progress.show(); self.compose_view.setText("Working…"); self.compose_view.show()
        self.idea_status.setText("Reading the idea, then every hit of each stem… this takes a few minutes the first time.")
        self.run(lambda log: actions.rebuild_layers(self.bp, self.folder, straight, octaves, log, idea=self.idea),
                 self.composed)

    def composed(self, res):
        self.idea, self.gen_bp, check, path = res; self.progress.hide()
        self.gen_report = check
        self.idea_view.setText("<br>".join("• " + x for x in actions.idea_summary(self.idea))); self.idea_view.show()
        g = self.bp["global"]
        k = self.idea["key"]
        reading = ("%s drone" % k["tonic"]) if not k.get("has_clear_third") else k["tonic"]
        self.facts.setText("%.1f BPM  ·  %s  ·  %d bars  ·  %d sections" % (g["tempo"], reading, g["n_bars"], len(self.bp["sections"])))
        rep = self.gen_bp["generation"]["report"]
        lines = []
        for name, r in rep.items():
            c = check.get(name, {})
            lines.append("<b>%s</b> from %s: %d notes. Matches the stem's own hits: %d%% found, %d%% false (score %.2f)."
                         % (name, r["from"], r["notes"], round(100 * c.get("found", 0)), round(100 * c.get("false", 0)),
                            c.get("hit_match", 0)))
        self.compose_view.setText("<b>Rebuilt from the audio.</b> Checked against the stems (not by ear):<br>%s<br>"
                                  "<span style='color:%s'>Saved: %s. Now choose <b>Rebuilt</b> in step 4 and listen.</span>"
                                  % ("<br>".join("• " + x for x in lines), theme.MUTED, Path(path).name))
        self.compose_view.show()
        self.idea_status.setText("Done. Same stems always give the same MIDI; change an octave box and press again to shift a layer.")
        self.rb_src_gen.setEnabled(True); self.rb_src_gen.setChecked(True)

    def show_rules(self):
        from .. import resynth
        self.logbox.show(); self.log_toggle.setText("Hide details")
        self.log("How the clean rebuild works:")
        for r in resynth.RULES:
            self.log("  - " + r)

    # ---- step 4
    def update_buttons(self):
        idle = not self.busy
        use_gen = self.rb_src_gen.isChecked() and self.gen_bp is not None
        use_new = self.rb_src_new.isChecked() and self.new_bp is not None
        ready = idle and (use_gen or use_new or (self.bp is not None and self.report is not None))
        self.btn_prev.setEnabled(ready); self.btn_mid.setEnabled(ready)
        arr_ok = self.live.get("connected") and self.live.get("arrangement")
        self.rb_arr.setToolTip("" if arr_ok else "Needs Stemforge's script installed and selected in Live (see the status pill).")
        self.btn_live.setEnabled(bool(ready and self.live.get("connected")))
        self.btn_compose.setEnabled(idle and self.bp is not None)

    def forced_stems(self) -> set[str]:
        out = set()
        for i in range(self.res_table.rowCount()):
            cell = self.res_table.cellWidget(i, 4)
            cb = cell.findChild(QCheckBox) if cell else None
            if cb is not None and cb.isChecked():
                out.add(self.res_table.item(i, 0).text())
        return out

    def build(self, target):
        use_new = self.rb_src_new.isChecked() and self.new_bp is not None
        use_gen = (not use_new) and self.rb_src_gen.isChecked() and self.gen_bp is not None
        bp = self.new_bp if use_new else (self.gen_bp if use_gen else self.bp)
        if not bp:
            return
        report = None if (use_gen or use_new) else self.report
        mode = "arrangement" if self.rb_arr.isChecked() else "session"
        include = set() if (use_gen or use_new) else self.forced_stems()
        if use_new:
            out_dir = str(Path(self.new_dir) / "midi")
        else:
            out_dir = str(Path(self.folder) / ("stemforge_rebuilt" if use_gen else "stemforge_midi"))
        self.progress.show(); self.outcome.setText("Working…")
        self.run(lambda log: actions.run_build(bp, report, mode=mode, target=target, out_dir=out_dir,
                                               set_tempo=self.cb_tempo.isChecked(), include=include, port=DEFAULT_PORT, log=log),
                 lambda s: self.built(s, target, out_dir, use_gen, use_new))

    def built(self, s, target, out_dir, composed=False, created=False):
        self.progress.hide(); self.update_buttons()
        what = ("song created from zero" if created else
                ("rebuilt version (clean Bass, Keys & Synth)" if composed else "transcription"))
        left = "".join("<br>Left out: %s (%s)" % (n, r) for n, r in s["excluded"].items())
        if target == "preview":
            head = ("Preview of the %s: would create %d tracks and %d clips (%d notes). Nothing was changed. See details."
                    % (what, s["tracks"], s["clips"], s["notes"]))
            self.logbox.show(); self.log_toggle.setText("Hide details")
        elif target == "midi":
            head = "Saved MIDI files of the %s to %s" % (what, out_dir)
        else:
            ok, total = s["readback"]
            color = theme.OK if ok == total else theme.BAD
            head = ("<span style='color:%s'>Built the %s in Ableton: %d tracks, %d clips. Checked by reading the notes back "
                    "from Live: %d of %d clips match.</span>" % (color, what, s["tracks"], s["clips"], ok, total))
        self.outcome.setText(head + left)


def selftest() -> int:
    """`stemforge-app --selftest`: check the parts a packaged build can lose, without opening a window or touching Live."""
    import importlib, json, os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    checks = {}
    for mod in ("numpy", "scipy", "librosa", "soundfile", "mido", "PySide6", "basic_pitch", "resampy"):
        try:
            importlib.import_module(mod); checks[mod] = "ok"
        except Exception as e:
            checks[mod] = "FAIL: %s" % e
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        checks["basic_pitch model file"] = "ok" if Path(str(ICASSP_2022_MODEL_PATH)).exists() else "FAIL: %s missing" % ICASSP_2022_MODEL_PATH
    except Exception as e:
        checks["basic_pitch model file"] = "FAIL: %s" % e
    try:
        checks["ableton script shipped"] = "ok (%s)" % installer.source_version()
    except Exception as e:
        checks["ableton script shipped"] = "FAIL: %s" % e
    try:
        import soundfile as sf
        checks["mp3 decoding (built in)"] = "ok" if "MP3" in sf.available_formats() else "MISSING: mp3 stems need ffmpeg (brew install ffmpeg)"
    except Exception as e:
        checks["mp3 decoding (built in)"] = "FAIL: %s" % e
    try:   # run the heavy parts for real on a 2 s tone: this is what a broken bundle loses (numba JIT, Core ML)
        import tempfile
        import librosa, numpy as np, soundfile as sf
        sr = 22050
        y = (0.5 * np.sin(2 * np.pi * 110.0 * np.arange(2 * sr) / sr)).astype("float32")
        f0, voiced, _ = librosa.pyin(y, fmin=30.0, fmax=400.0, sr=sr)
        hz = float(np.nanmedian(f0))
        checks["pitch tracker (pyin) runs"] = "ok (%.0f Hz)" % hz if 100 < hz < 120 else "FAIL: got %.1f Hz" % hz
        from basic_pitch.inference import predict
        with tempfile.TemporaryDirectory() as d:
            sf.write(d + "/t.wav", y, sr)
            _, _, events = predict(d + "/t.wav")
        checks["note transcriber (Basic Pitch) runs"] = "ok (%d notes)" % len(events)
    except Exception as e:
        checks["heavy parts run"] = "FAIL: %s: %s" % (type(e).__name__, e)
    try:
        from .. import resynth as resynth_mod, idea as idea_mod
        checks["idea + rebuild modules"] = "ok (%d rules)" % len(resynth_mod.RULES)
        checks["tempo-synced notes"] = "ok" if any("357 ms" in n for n in idea_mod.production_notes(126.0)) else "FAIL: wrong delay time"
    except Exception as e:
        checks["idea + rebuild modules"] = "FAIL: %s: %s" % (type(e).__name__, e)
    try:
        from ..styles import create as styles_create
        made = [styles_create.create(st) for st in styles_create.STYLES]
        checks["create from zero (4 styles)"] = "ok (%s)" % ", ".join("%s %d notes" % (b["generation"]["style"], sum(len(c["notes"]) for c in b["clips"])) for b in made)
    except Exception as e:
        checks["create from zero (4 styles)"] = "FAIL: %s: %s" % (type(e).__name__, e)
    print(json.dumps(checks, indent=1))
    return 0 if not any(v.startswith("FAIL") for v in checks.values()) else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    import os   # an app started from Finder has a minimal PATH: let it find Homebrew's ffmpeg for odd formats
    os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.QSS)
    w = Window(); w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
