BG = "#16171b"
CARD = "#1f2127"
LINE = "#2d3038"
TEXT = "#e8e9ec"
MUTED = "#9a9fab"
ACCENT = "#ff6a3d"      # Ableton-ish orange
OK = "#4cc38a"
WARN = "#f2b84b"
BAD = "#ef6a6a"

SECTION_COLORS = {
    "intro": "#4b6a9b", "groove": "#3f8f7a", "build": "#c28b3c", "drop": "#d2553f",
    "peak": "#d2553f", "breakdown": "#7a5aa6", "outro": "#5d6270",
}

QSS = f"""
* {{ font-family: -apple-system, "SF Pro Text", "Helvetica Neue", Arial; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QLabel#h1 {{ font-size: 20px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 650; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#step {{ background: {ACCENT}; color: #111; border-radius: 11px; font-weight: 700; min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; qproperty-alignment: AlignCenter; }}
QFrame#drop {{ border: 2px dashed {LINE}; border-radius: 12px; background: {BG}; }}
QFrame#drop[hover="true"] {{ border-color: {ACCENT}; }}
QPushButton {{ background: {LINE}; border: none; border-radius: 8px; padding: 8px 14px; }}
QPushButton:hover {{ background: #3a3e48; }}
QPushButton:disabled {{ color: #666b77; background: #23252b; }}
QPushButton#primary {{ background: {ACCENT}; color: #111; font-weight: 700; }}
QPushButton#primary:hover {{ background: #ff7e57; }}
QPushButton#primary:disabled {{ background: #5b3a2f; color: #8c7a74; }}
QTableWidget {{ background: {CARD}; border: none; gridline-color: {LINE}; selection-background-color: #2a2d36; }}
QHeaderView::section {{ background: {CARD}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE}; padding: 6px; }}
QComboBox, QPlainTextEdit {{ background: {BG}; border: 1px solid {LINE}; border-radius: 6px; padding: 4px 8px; }}
QProgressBar {{ background: {BG}; border: none; border-radius: 4px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QScrollArea {{ border: none; }}
"""
