"""Draw the Stemforge app icon and write packaging/Stemforge.icns (macOS: needs `iconutil`).

Run from the repo root with the project's venv:  python packaging/make_icon.py
The icon: a dark macOS-style rounded square; on the left, audio stems as waveform bars; on the right, the same energy
as MIDI notes on a piano-roll, in the app's accent colours. "Audio in, MIDI out".
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,  # noqa: E402
                           QRadialGradient)

SIZE = 1024
OUT = Path(__file__).resolve().parent


def draw() -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    # macOS icon grid: the squircle fills ~80% of the canvas
    m = SIZE * 0.10
    body = QRectF(m, m, SIZE - 2 * m, SIZE - 2 * m)
    path = QPainterPath()
    path.addRoundedRect(body, 190, 190)
    p.setClipPath(path)
    bg = QLinearGradient(body.topLeft(), body.bottomRight())
    bg.setColorAt(0.0, QColor("#2a2d36"))
    bg.setColorAt(1.0, QColor("#121317"))
    p.fillPath(path, bg)
    glow = QRadialGradient(QPointF(body.center().x() + 120, body.center().y()), 420)
    glow.setColorAt(0.0, QColor(255, 106, 61, 70))
    glow.setColorAt(1.0, QColor(255, 106, 61, 0))
    p.fillRect(body, glow)

    inner = body.adjusted(86, 150, -86, -150)
    mid = inner.center().x()
    # left: audio stems as waveform bars (rounded, varied heights, cool grey-blue)
    n_bars = 9
    gap = 14
    bar_w = (mid - inner.left() - 40 - gap * (n_bars - 1)) / n_bars
    for i in range(n_bars):
        h = inner.height() * (0.22 + 0.62 * abs(math.sin(i * 0.9 + 0.6)) * (0.55 + 0.45 * math.cos(i * 0.35)))
        x = inner.left() + i * (bar_w + gap)
        r = QRectF(x, inner.center().y() - h / 2, bar_w, h)
        c = QColor("#8d97ad")
        c.setAlpha(int(110 + 120 * (i / (n_bars - 1))))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, bar_w / 2, bar_w / 2)

    # right: the same material as MIDI notes in five rows (piano roll)
    rows = 5
    row_h = inner.height() / (rows * 1.55)
    x0 = mid + 40
    width = inner.right() - x0
    palette = ["#ff6a3d", "#f2b84b", "#4cc38a", "#6aa9ff", "#ff6a3d"]
    notes = [
        [(0.00, 0.30), (0.42, 0.20), (0.70, 0.30)],
        [(0.10, 0.18), (0.34, 0.30), (0.74, 0.26)],
        [(0.00, 0.50), (0.58, 0.40)],
        [(0.18, 0.22), (0.46, 0.16), (0.68, 0.32)],
        [(0.04, 0.24), (0.36, 0.34), (0.78, 0.22)],
    ]
    top = inner.center().y() - (rows * row_h * 1.35) / 2
    for r_i in range(rows):
        y = top + r_i * row_h * 1.35
        for s, ln in notes[r_i]:
            nr = QRectF(x0 + s * width, y, ln * width, row_h)
            col = QColor(palette[r_i])
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(nr, row_h * 0.32, row_h * 0.32)

    # a thin spark line between the two halves: the conversion
    pen = QPen(QColor("#ff6a3d"), 8)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(mid, inner.top() + 30), QPointF(mid, inner.bottom() - 30))

    # soft top-light for depth
    p.setClipPath(path)
    sheen = QLinearGradient(body.topLeft(), QPointF(body.left(), body.top() + body.height() * 0.5))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 34))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(body, sheen)
    p.end()
    return img


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    img = draw()
    img.save(str(OUT / "Stemforge_icon_1024.png"))
    sizes = {"icon_16x16.png": 16, "icon_16x16@2x.png": 32, "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
             "icon_128x128.png": 128, "icon_128x128@2x.png": 256, "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
             "icon_512x512.png": 512, "icon_512x512@2x.png": 1024}
    with tempfile.TemporaryDirectory() as d:
        iconset = Path(d) / "Stemforge.iconset"
        iconset.mkdir()
        for name, px in sizes.items():
            img.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(iconset / name))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "Stemforge.icns")], check=True)
    print("wrote", OUT / "Stemforge.icns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
