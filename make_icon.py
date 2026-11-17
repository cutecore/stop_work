"""写出 exe 用的图标。只在打包时调用。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication.instance() or QApplication([])
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0A0908"))
    painter.drawRoundedRect(16, 16, 224, 224, 16, 16)
    painter.setBrush(QColor("#FF6A00"))
    for index in range(6):
        y = 52 + index * 28
        painter.drawRect(84, y, 88, 18)
    painter.end()
    path = Path(__file__).with_name("stopwork.ico")
    if not pixmap.save(str(path), "ICO"):
        raise SystemExit("failed to write " + str(path))
    del app


if __name__ == "__main__":
    main()
