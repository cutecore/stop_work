"""始终浮在桌面上的休息面板。只留装甲中间的黑板和倒计时。"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from engine import View, format_countdown
from store import log, save_state

if TYPE_CHECKING:
    from engine import Engine
    from monitor import ActivityMonitor

# 参考画布 1500×600。留下中间黑板、右侧电源框和底部档位，不含左边斜腿和四周底纹。
CROP_X = 500.0
CROP_Y = 104.0
CROP_W = 924.0
CROP_H = 392.0
SCALE = 0.40
WIN_W = round(CROP_W * SCALE)
WIN_H = round(CROP_H * SCALE)
LOW_BATTERY = 0.22

AMBER = QColor("#ffac1e")
RED = QColor("#ff2415")
CYAN = QColor("#3fd8ff")
BLACK = QColor("#000000")

MINCHO_FILE = Path(r"C:\Users\cutec\Documents\方正字库\Font\FZFWZhuZiAOldMinchoR.TTF")
_MINCHO_FAMILY: str | None = None

PLATE = [
    (515, 118),
    (742, 118),
    (759.4, 146.7),
    (1410, 146.7),
    (1410, 484),
    (583, 484),
    (583, 222),
    (515, 222),
]
LEG = [
    (515, 222),
    (583, 222),
    (583, 420),
    (515, 420),
    (437, 530.5),
    (352, 502.5),
]
NOTCH = [
    (492, 118),
    (514, 118),
    (514, 170),
    (491, 164),
    (488, 160),
    (488, 126),
]
SLOT = [
    (348, 509.5),
    (433, 537.5),
    (388.9, 600),
    (295.4, 600),
]
FLOOR = [
    (440, 600),
    (560, 488),
    (1500, 488),
    (1500, 600),
]

SEG_MASK = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
    "-": "g",
}


def _poly(points: list[tuple[float, float]]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _load_family(path: Path, cache: list[str | None]) -> str | None:
    if cache[0] is not None:
        return cache[0] or None
    if path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        cache[0] = families[0] if families else ""
    else:
        cache[0] = ""
    return cache[0] or None


def mincho_family() -> str | None:
    global _MINCHO_FAMILY
    family = _load_family(MINCHO_FILE, [_MINCHO_FAMILY])
    _MINCHO_FAMILY = family or ""
    return family


def make_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(["Bahnschrift", "Segoe UI", "Microsoft YaHei UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setKerning(False)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def make_en_font(size: float, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    font = QFont("Arial")
    font.setPixelSize(max(1, int(round(size))))
    font.setWeight(weight)
    font.setKerning(False)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def make_mincho(size: float) -> QFont:
    family = mincho_family()
    font = QFont(family) if family else make_jp_font(int(size))
    font.setPixelSize(max(1, int(round(size))))
    font.setWeight(QFont.Weight.Bold)
    font.setKerning(False)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def make_jp_font(size: int, weight: QFont.Weight = QFont.Weight.Black) -> QFont:
    font = QFont()
    font.setFamilies(["Yu Gothic UI", "Yu Gothic", "Meiryo UI", "Microsoft YaHei UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setKerning(False)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def make_icon() -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(AMBER, 3))
    painter.setBrush(BLACK)
    painter.drawPolygon(
        _poly([(8, 14), (28, 14), (34, 22), (56, 22), (56, 50), (8, 50)])
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(AMBER)
    _paint_digit(painter, QRectF(22, 26, 20, 20), 4, "8", AMBER, ghost=False)
    painter.end()
    return QIcon(pixmap)


def clamp_position(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    screens = QGuiApplication.screens()
    if not screens:
        return x, y
    cx = x + width / 2
    cy = y + height / 2
    best = screens[0].availableGeometry()
    best_distance: float | None = None
    for screen in screens:
        geo = screen.availableGeometry()
        nearest_x = min(max(cx, geo.left()), geo.right())
        nearest_y = min(max(cy, geo.top()), geo.bottom())
        distance = (nearest_x - cx) ** 2 + (nearest_y - cy) ** 2
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = geo
    margin = 28
    min_cx = best.left() + margin
    max_cx = max(min_cx, best.right() - margin)
    min_cy = best.top() + margin
    max_cy = max(min_cy, best.bottom() - margin)
    next_cx = min(max(cx, min_cx), max_cx)
    next_cy = min(max(cy, min_cy), max_cy)
    return int(round(x + next_cx - cx)), int(round(y + next_cy - cy))


def default_position(width: int, height: int) -> tuple[int, int]:
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    geo = screen.availableGeometry() if screen is not None else QRectF(0, 0, 1280, 720)
    x = int(geo.right() - width - 16)
    y = int(geo.top() + 16)
    return clamp_position(x, y, width, height)


def pin_topmost(hwnd: int) -> None:
    if not hwnd:
        return
    import ctypes

    HWND_TOPMOST = -1
    flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
    ctypes.windll.user32.SetWindowPos(
        ctypes.c_void_p(hwnd),
        ctypes.c_void_p(HWND_TOPMOST),
        0,
        0,
        0,
        0,
        flags,
    )


def _digit_parts(x: float, y: float, w: float, h: float, thickness: float) -> dict[str, QPolygonF]:
    gap = thickness * 0.28
    inset = thickness * 0.08

    def horizontal(top: float) -> QPolygonF:
        left = x + inset
        right = x + w - inset
        point = thickness * 0.48
        return _poly(
            [
                (left + point, top),
                (right - point, top),
                (right, top + thickness / 2),
                (right - point, top + thickness),
                (left + point, top + thickness),
                (left, top + thickness / 2),
            ]
        )

    def vertical(left: float, top: float, height: float) -> QPolygonF:
        point = thickness * 0.46
        return _poly(
            [
                (left + thickness / 2, top),
                (left + thickness, top + point),
                (left + thickness, top + height - point),
                (left + thickness / 2, top + height),
                (left, top + height - point),
                (left, top + point),
            ]
        )

    mid = y + (h - thickness) / 2
    upper_top = y + thickness + gap * 0.35
    upper_h = mid - upper_top
    lower_top = mid + thickness + gap * 0.35
    lower_h = (y + h - thickness) - lower_top
    return {
        "a": horizontal(y),
        "g": horizontal(mid),
        "d": horizontal(y + h - thickness),
        "f": vertical(x, upper_top, upper_h),
        "b": vertical(x + w - thickness, upper_top, upper_h),
        "e": vertical(x, lower_top, lower_h),
        "c": vertical(x + w - thickness, lower_top, lower_h),
    }


def _paint_digit(
    painter: QPainter,
    box: QRectF,
    thickness: float,
    char: str,
    color: QColor,
    *,
    ghost: bool,
) -> None:
    parts = _digit_parts(box.x(), box.y(), box.width(), box.height(), thickness)
    lit = SEG_MASK.get(char, "")
    ghost_color = QColor(color)
    ghost_color.setAlpha(28 if ghost else 18)
    painter.setPen(Qt.PenStyle.NoPen)
    for name, polygon in parts.items():
        on = name in lit
        if not on:
            painter.setBrush(ghost_color)
            painter.drawPolygon(polygon)
            continue
        glow = QColor(color)
        glow.setAlpha(110)
        painter.setBrush(glow)
        painter.drawPolygon(polygon)
        painter.setBrush(color)
        painter.drawPolygon(polygon)


def _paint_colon(painter: QPainter, x: float, y: float, height: float, size: float, color: QColor) -> None:
    center = y + height / 2
    gap = max(size * 1.15, height * 0.16)
    painter.setPen(Qt.PenStyle.NoPen)
    glow = QColor(color)
    glow.setAlpha(90)
    for top in (center - gap - size, center + gap):
        painter.setBrush(glow)
        painter.drawRect(QRectF(x - 1.5, top - 1.5, size + 3, size + 3))
        painter.setBrush(color)
        painter.drawRect(QRectF(x, top, size, size))


def _glow_text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    font: QFont,
    color: QColor,
    flags: int,
) -> None:
    painter.setFont(font)
    glow = QColor(color)
    glow.setAlpha(80)
    painter.setPen(glow)
    for dx, dy in ((-1.4, 0), (1.4, 0), (0, -1.4), (0, 1.4)):
        painter.drawText(rect.translated(dx, dy), flags, text)
    painter.setPen(color)
    painter.drawText(rect, flags, text)


def _fitted_en(text: str, max_width: float, size: float, floor: float = 8) -> QFont:
    px = size
    while px >= floor:
        font = make_en_font(px)
        if QFontMetrics(font).horizontalAdvance(text) <= max_width:
            return font
        px -= 0.5
    return make_en_font(floor)


def _spread_line(
    painter: QPainter,
    rect: QRectF,
    text: str,
    font: QFont,
    color: QColor,
) -> None:
    """字距只拉开能放下的字，避免小框里叠成一团。"""
    size = font.pixelSize()
    chosen = QFont(font)
    widths = [rect.width()]
    while size >= 6:
        trial = QFont(font)
        trial.setPixelSize(size)
        metrics = QFontMetrics(trial)
        widths = [metrics.horizontalAdvance(char) for char in text]
        if sum(widths) <= rect.width():
            chosen = trial
            break
        size -= 1
    else:
        _glow_text(
            painter,
            rect,
            text,
            chosen,
            color,
            int(Qt.AlignmentFlag.AlignCenter),
        )
        return
    metrics = QFontMetrics(chosen)
    extra = rect.width() - sum(widths)
    gap = extra / (len(text) - 1) if len(text) > 1 else 0
    baseline = rect.bottom() - metrics.descent()
    x = rect.x()
    painter.save()
    painter.setClipRect(rect.adjusted(-1, -3, 1, 2))
    painter.setFont(chosen)
    for char, width in zip(text, widths):
        painter.setPen(color)
        painter.drawText(QPointF(x, baseline), char)
        x += width + gap
    painter.restore()


class FloatWindow(QWidget):
    def __init__(
        self,
        engine: Engine,
        monitor: ActivityMonitor,
        pos: tuple[int, int] | None = None,
        frozen: bool = False,
    ) -> None:
        super().__init__(None)
        self.engine = engine
        self.monitor = monitor
        self._frozen = frozen
        self._forced_view: View | None = None
        self._hover = False
        self._drag: QPoint | None = None
        self._dragged = False
        self._bonus = 0.0
        self._last_frame = time.monotonic()
        self._ensure_acc = 0.0
        self._save_acc = 0.0
        self._reported_unhealthy = False

        self.setWindowTitle("Stop Work")
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        self._menu = QMenu(self)
        self._menu.setFont(make_font(12))
        self._menu.setStyleSheet(
            """
            QMenu {
                background-color: #000000;
                color: #ffac1e;
                border: 1px solid #ffac1e;
                border-radius: 0px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 18px;
            }
            QMenu::item:selected {
                background-color: #2a1a08;
                color: #ffac1e;
            }
            """
        )
        quit_action = self._menu.addAction("QUIT")
        quit_action.triggered.connect(QApplication.quit)

        if pos is None:
            x, y = default_position(WIN_W, WIN_H)
        else:
            x, y = clamp_position(pos[0], pos[1], WIN_W, WIN_H)
        self.move(x, y)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._on_frame)
        if not frozen:
            self._timer.start()

    def set_forced_view(self, view: View | None) -> None:
        self._forced_view = view
        self.update()

    def bring(self) -> None:
        if self._frozen:
            return
        state = self.windowState()
        if state & Qt.WindowState.WindowMinimized:
            self.setWindowState(state & ~Qt.WindowState.WindowMinimized)
        if not self.isVisible():
            self.show()
        pin_topmost(int(self.winId()))
        self.ensure_on_screen()

    def ensure_on_screen(self) -> None:
        x, y = clamp_position(self.x(), self.y(), self.width(), self.height())
        if x != self.x() or y != self.y():
            self.move(x, y)

    def persist(self) -> None:
        if self._frozen:
            return
        save_state(self.engine.battery, self.x(), self.y())

    def _on_frame(self) -> None:
        now = time.monotonic()
        frame_dt = max(0.0, now - self._last_frame)
        self._last_frame = now
        if self.monitor.healthy():
            self._reported_unhealthy = False
            self.engine.poll(now, self.monitor.last_input())
            if self.engine.consume_emptied():
                self._bonus = 1.0
                log("battery empty")
        elif not self._reported_unhealthy:
            self._reported_unhealthy = True
            log("input monitor stopped: " + (self.monitor.error or "not alive"))

        if self._bonus > 0:
            self._bonus = max(0.0, self._bonus - frame_dt / 1.6)

        self._ensure_acc += frame_dt
        if self._ensure_acc >= 1:
            self._ensure_acc = 0
            self._keep_present()

        self._save_acc += frame_dt
        if self._save_acc >= 5:
            self._save_acc = 0
            self.persist()
        self.update()

    def _keep_present(self) -> None:
        hidden = (not self.isVisible()) or bool(self.windowState() & Qt.WindowState.WindowMinimized)
        if hidden:
            self.bring()
            return
        pin_topmost(int(self.winId()))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        now = time.monotonic()
        view = self._forced_view if self._forced_view is not None else self.engine.view(now)
        healthy = True if self._forced_view is not None else self.monitor.healthy()
        alert = healthy and (
            view.kind == "empty" or (view.kind == "work" and view.level <= LOW_BATTERY)
        )
        ink = QColor(RED if alert else AMBER)
        if alert and view.kind == "empty":
            ink.setAlpha(255 if (now * 2.5) % 1.0 < 0.62 else 70)
        elif alert:
            ink.setAlpha(int(180 + 75 * (0.5 + 0.5 * math.sin(now * 9.0))))

        sx = self.width() / CROP_W
        sy = self.height() / CROP_H
        painter.scale(sx, sy)
        painter.translate(-CROP_X, -CROP_Y)
        self._paint_armor(painter, ink)
        self._paint_title(painter, ink)
        readout = format_countdown(view.hero_seconds) if healthy else "--:--:--"
        self._paint_readout(painter, readout, ink)
        self._paint_supply(painter, view, healthy, ink, now)
        self._paint_modes(painter, view, healthy, ink, alert, now)
        self._paint_danger(painter, alert, now)
        self._paint_subscribe(painter)

    def _paint_ground(self, painter: QPainter) -> None:
        gradient = QLinearGradient(QPointF(200, 600), QPointF(1500, 0))
        stops = (
            (0.00, "#b2403c"),
            (0.20, "#b58a3a"),
            (0.30, "#a9be4a"),
            (0.38, "#81ba5d"),
            (0.64, "#55995a"),
            (0.80, "#3f8aa0"),
            (0.92, "#3f68ae"),
            (1.00, "#4b4fb0"),
        )
        for offset, color in stops:
            gradient.setColorAt(offset, QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRect(QRectF(CROP_X - 4, CROP_Y - 4, CROP_W + 8, CROP_H + 8))
        painter.setBrush(BLACK)
        painter.drawRect(QRectF(CROP_X - 4, 0, CROP_W + 8, 48))
        painter.drawPolygon(_poly(FLOOR))
        painter.drawRect(QRectF(200, 0, 10, 600))
        painter.drawRect(QRectF(220, 0, 5, 600))

    def _paint_armor(self, painter: QPainter, ink: QColor) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BLACK)
        painter.drawPolygon(_poly(PLATE))
        pen = QPen(ink, 2.4)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        pen.setMiterLimit(2.4)
        glow = QColor(ink)
        glow.setAlpha(120)
        glow_pen = QPen(glow, 7.0)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        glow_pen.setMiterLimit(2.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        polygon = _poly(PLATE)
        painter.setPen(glow_pen)
        painter.drawPolygon(polygon)
        painter.setPen(pen)
        painter.drawPolygon(polygon)

    def _paint_ticks(self, painter: QPainter, ink: QColor) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CYAN)
        x = 200.0
        while x < CROP_X + CROP_W:
            painter.drawRect(QRectF(x, 34, 3, 9))
            painter.drawRect(QRectF(x + 12, 34, 3, 9))
            x += 100
        painter.setBrush(BLACK)
        x = 248.0
        while x < 1400:
            painter.drawRect(QRectF(x, 50, 3, 11))
            x += 100
        painter.setBrush(CYAN)
        for mark in (568, 629, 724, 769, 864, 909, 1004, 1049, 1144, 1199, 1303, 1398):
            painter.drawRect(QRectF(mark, 490, 3, 8))
        for mark in (568, 629, 746.5, 886.5, 1026.5, 1171.5, 1303, 1398):
            painter.drawRect(QRectF(mark, 506, 3, 8))
        y = 72.0
        while y < 590:
            painter.drawRect(QRectF(201.5, y, 7, 2))
            y += 40
        painter.setBrush(ink)
        for mark in (603, 608, 745, 749, 885, 889, 1025, 1029, 1173, 1178, 1303, 1307, 1398, 1402):
            painter.drawRect(QRectF(mark, 424, 2, 10))

    def _paint_title(self, painter: QPainter, ink: QColor) -> None:
        title_font = make_mincho(40)
        title_font.setStretch(92)
        _glow_text(
            painter,
            QRectF(518, 108, 250, 62),
            "活動限界まで",
            title_font,
            ink,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )
        en_font = _fitted_en("ACTIVE TIME REMAINING:", 430, 23, 14)
        _glow_text(
            painter,
            QRectF(752, 146, 450, 30),
            "ACTIVE TIME REMAINING:",
            en_font,
            ink,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )
        ato = make_mincho(28)
        _glow_text(
            painter,
            QRectF(526, 176, 80, 36),
            "あと",
            ato,
            ink,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )

    def _paint_readout(self, painter: QPainter, text: str, ink: QColor) -> None:
        digits = "".join(char for char in text if char.isdigit() or char == "-")
        if len(digits) < 6:
            digits = digits.rjust(6, "0" if digits.isdigit() else "-")
        digits = digits[-6:]
        big = (92.0, 196.0, 20.0)
        small = (60.0, 132.0, 14.0)
        y = 196.0
        places = (
            (598.0, y, *big),
            (700.0, y, *big),
            (828.0, y, *big),
            (930.0, y, *big),
            (1052.0, y + big[1] - small[1], *small),
            (1122.0, y + big[1] - small[1], *small),
        )
        for char, (x, top, width, height, thickness) in zip(digits, places):
            _paint_digit(painter, QRectF(x, top, width, height), thickness, char, ink, ghost=True)
        _paint_colon(painter, 806, y, big[1], 13, ink)
        _paint_colon(painter, 1034, y + big[1] - small[1], small[1], 9, ink)

    def _supply_name(self, view: View, healthy: bool) -> str:
        if not healthy:
            return ""
        if view.kind in ("rest", "paused"):
            return "external"
        return "internal"

    def _paint_supply(
        self,
        painter: QPainter,
        view: View,
        healthy: bool,
        ink: QColor,
        now: float,
    ) -> None:
        active = self._supply_name(view, healthy)
        pulse = 0.9 + 0.1 * math.sin(now * 3.4)
        self._paint_mode_box(
            painter,
            QRectF(1216, 182, 182, 84),
            "内部",
            "INTERNAL",
            ink,
            active=active == "internal",
            zebra=active == "internal",
            pulse=pulse,
        )
        self._paint_power(painter, ink, pulse if healthy else 0.45)
        self._paint_mode_box(
            painter,
            QRectF(1216, 328, 182, 84),
            "外部",
            "EXTERNAL",
            ink,
            active=active == "external",
            zebra=active == "external",
            pulse=pulse,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CYAN)
        for top, height in ((173, 8), (267, 8), (319, 8), (414, 5)):
            painter.drawRect(QRectF(1216, top, 3, height))
            painter.drawRect(QRectF(1395, top, 3, height))

    def _paint_mode_box(
        self,
        painter: QPainter,
        box: QRectF,
        jp: str,
        en: str,
        ink: QColor,
        *,
        active: bool,
        zebra: bool,
        pulse: float,
    ) -> None:
        painter.save()
        painter.setOpacity(1.0 if active else 0.36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BLACK)
        painter.drawRoundedRect(box, 3, 3)
        if zebra:
            self._paint_zebra(painter, QRectF(box.right() - 40, box.top(), 40, box.height()))
        pen = QPen(ink, 2.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 3, 3)
        if active:
            glow = QColor(ink)
            glow.setAlpha(int(70 * pulse))
            painter.setPen(QPen(glow, 6))
            painter.drawRoundedRect(box, 3, 3)
        jp_font = make_jp_font(52, QFont.Weight.Black)
        en_font = _fitted_en(en, box.width() - 56, 22, 12)
        color = QColor(ink)
        if active:
            color.setAlpha(int(255 * min(1.0, pulse + 0.05)))
        _glow_text(
            painter,
            QRectF(box.x() + 8, box.y() - 2, box.width() - 50, 58),
            jp,
            jp_font,
            color,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )
        _glow_text(
            painter,
            QRectF(box.x() + 8, box.bottom() - 30, box.width() - 52, 26),
            en,
            en_font,
            color,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )
        painter.restore()

    def _paint_power(self, painter: QPainter, ink: QColor, pulse: float) -> None:
        box = QRectF(1216, 276, 182, 42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BLACK)
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QPen(ink, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 3, 3)
        glow = QColor(ink)
        glow.setAlpha(int(80 * pulse))
        painter.setPen(QPen(glow, 5))
        painter.drawRoundedRect(box, 3, 3)
        jp_font = make_jp_font(15, QFont.Weight.Bold)
        en = "MAIN ENERGY SUPPLY SYSTEM"
        en_font = _fitted_en(en, box.width() - 12, 10.5, 8)
        color = QColor(ink)
        color.setAlpha(int(210 + 45 * pulse))
        _glow_text(
            painter,
            QRectF(box.x() + 6, box.y() + 1, box.width() - 10, 22),
            "主電源供給システム",
            jp_font,
            color,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )
        _glow_text(
            painter,
            QRectF(box.x() + 6, box.bottom() - 16, box.width() - 10, 14),
            en,
            en_font,
            color,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        )

    def _paint_zebra(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#150202"))
        painter.drawRect(rect)
        painter.setBrush(QColor("#e8000e"))
        band = 10.0
        x = rect.left() - rect.height()
        while x < rect.right() + band:
            painter.drawPolygon(
                _poly(
                    [
                        (x, rect.bottom()),
                        (x + band, rect.bottom()),
                        (x + band + rect.height(), rect.top()),
                        (x + rect.height(), rect.top()),
                    ]
                )
            )
            x += band * 2
        painter.restore()

    def _mode_index(self, view: View, healthy: bool) -> int:
        if not healthy or view.kind == "empty" or view.level <= 0.002:
            return 0
        if view.level <= LOW_BATTERY:
            return 1
        if view.level >= 0.9:
            return 3
        return 2

    def _paint_modes(
        self,
        painter: QPainter,
        view: View,
        healthy: bool,
        ink: QColor,
        alert: bool,
        now: float,
    ) -> None:
        labels = ("STOP", "SLOW", "NORMAL", "RACING")
        selected = self._mode_index(view, healthy) if healthy else -1
        lefts = (628.0, 768.0, 908.0, 1048.0)
        blink = 1.0 if not alert else (1.0 if math.sin(now * 10) > 0 else 0.35)
        for index, (label, left) in enumerate(zip(labels, lefts)):
            cell = QRectF(left, 428, 100, 48)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#030100"))
            painter.drawRoundedRect(cell, 3, 3)
            if index == selected:
                red = QColor("#fff4f1" if alert else "#ff2a18")
                red.setAlpha(int(255 * blink))
                painter.setBrush(red)
                painter.drawRect(
                    QRectF(cell.x() + 3, cell.center().y() + 2, cell.width() - 6, cell.height() / 2 - 5)
                )
            painter.setPen(QPen(ink, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(cell, 3, 3)
            font = _fitted_en(label, cell.width() - 8, 21, 12)
            _glow_text(
                painter,
                cell.adjusted(2, 0, -2, 0),
                label,
                font,
                ink,
                int(Qt.AlignmentFlag.AlignCenter),
            )

    def _paint_danger(self, painter: QPainter, alert: bool, now: float) -> None:
        cell = QRectF(1200, 428, 100, 48)
        painter.save()
        if alert:
            painter.setOpacity(1.0 if math.sin(now * 12) > 0 else 0.28)
        else:
            painter.setOpacity(0.24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#030100"))
        painter.drawRoundedRect(cell, 3, 3)
        painter.setPen(QPen(RED, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(cell, 3, 3)
        glow = QColor(RED)
        glow.setAlpha(140)
        painter.setPen(QPen(glow, 5))
        painter.drawRoundedRect(cell, 3, 3)
        inner = cell.adjusted(5, 5, -5, -4)
        _spread_line(painter, QRectF(inner.x(), inner.y(), inner.width(), 20), "DANGER", make_en_font(15), RED)
        _spread_line(
            painter,
            QRectF(inner.x(), inner.bottom() - 14, inner.width(), 14),
            "EMERGENCY",
            make_en_font(9),
            RED,
        )
        painter.restore()

    def _paint_subscribe(self, painter: QPainter) -> None:
        cell = QRectF(1312, 428, 84, 48)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#030100"))
        painter.drawRoundedRect(cell, 3, 3)
        painter.setPen(QPen(RED, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(cell, 3, 3)
        inner = cell.adjusted(4, 3, -4, -2)
        _spread_line(
            painter,
            QRectF(inner.x(), inner.y(), inner.width(), 16),
            "登録する",
            make_jp_font(13, QFont.Weight.Bold),
            RED,
        )
        _glow_text(
            painter,
            QRectF(inner.x(), inner.y() + 16, inner.width(), 12),
            "SUBSCRIBE",
            _fitted_en("SUBSCRIBE", inner.width(), 9, 7),
            RED,
            int(Qt.AlignmentFlag.AlignCenter),
        )
        _glow_text(
            painter,
            QRectF(inner.x(), inner.bottom() - 10, inner.width(), 9),
            "Code.Villkiss",
            _fitted_en("Code.Villkiss", inner.width(), 6.5, 5),
            RED,
            int(Qt.AlignmentFlag.AlignCenter),
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        if self._drag is None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        if self._drag is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._menu.popup(event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        self._dragged = True
        origin = event.globalPosition().toPoint() - self._drag
        x, y = clamp_position(origin.x(), origin.y(), self.width(), self.height())
        self.move(x, y)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if self._hover else Qt.CursorShape.ArrowCursor
        )
        if self._dragged:
            self.persist()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if self._frozen:
            return
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.bring)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.persist()
        super().closeEvent(event)
