"""始终浮在桌面上的休息卡片。EVA 风：工作放电，休息充电。"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from engine import REST_MINUTES, WORK_MINUTES, View, format_duration
from store import log, save_state

if TYPE_CHECKING:
    from engine import Engine
    from monitor import ActivityMonitor

PAD = 16
CARD_W = 176
CARD_H = 86
WIN_W = CARD_W + PAD * 2
WIN_H = CARD_H + PAD * 2
CORNER = 10
SEGMENTS = 10
LOW_BATTERY = 0.22

THEMES = {
    "work": {
        "top": "#14120F",
        "bottom": "#0A0908",
        "text": "#F4EDE3",
        "muted": "#B89A78",
        "accent": "#FF6A00",
        "track": "#2A1E14",
        "dot": "#FF6A00",
        "line": "#FF6A00",
    },
    "paused": {
        "top": "#121110",
        "bottom": "#080807",
        "text": "#D8CFC3",
        "muted": "#7E7366",
        "accent": "#9A6B3A",
        "track": "#241C16",
        "dot": "#8A7A68",
        "line": "#6E5A44",
    },
    "rest": {
        "top": "#0C1410",
        "bottom": "#070B09",
        "text": "#E8FFE8",
        "muted": "#7CB88A",
        "accent": "#7CFF4A",
        "track": "#15241A",
        "dot": "#7CFF4A",
        "line": "#7CFF4A",
    },
    "empty": {
        "top": "#1C0C0C",
        "bottom": "#100606",
        "text": "#FFE4DE",
        "muted": "#D07870",
        "accent": "#FF2A2A",
        "track": "#2E1010",
        "dot": "#FF2A2A",
        "line": "#FF2A2A",
    },
}


def make_font(
    size: int,
    weight: QFont.Weight = QFont.Weight.Normal,
    *,
    digits: bool = False,
) -> QFont:
    font = QFont()
    if digits:
        font.setFamilies(["Cascadia Mono", "Consolas", "Segoe UI"])
    else:
        font.setFamilies(["Cascadia Mono", "Consolas", "Microsoft YaHei UI", "Segoe UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6 if not digits else 0.0)
    font.setKerning(False)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def make_icon() -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0A0908"))
    painter.drawRoundedRect(4, 4, 56, 56, 4, 4)
    painter.setBrush(QColor("#FF6A00"))
    for index in range(6):
        y = 14 + index * 7
        painter.drawRect(22, y, 20, 5)
    painter.end()
    return QIcon(pixmap)


def copy_for(view: View) -> tuple[str, str]:
    if view.kind == "work":
        return "DRAIN", f"INTERNAL · {WORK_MINUTES}m"
    if view.kind == "paused":
        return "STANDBY", "Battery full"
    if view.kind == "rest":
        return "CHARGE", f"EXT POWER · {REST_MINUTES}m"
    return "EMPTY", "Charge required"


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
    x = int(geo.right() - PAD - CARD_W - 12)
    y = int(geo.top() + 12 - PAD)
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


def draw_time(painter: QPainter, x: float, baseline: float, text: str, color: QColor) -> float:
    metrics = painter.fontMetrics()
    digit = metrics.horizontalAdvance("0")
    cursor = x
    painter.setPen(color)
    for char in text:
        if char.isdigit():
            cell = digit
            char_width = metrics.horizontalAdvance(char)
            painter.drawText(int(cursor + (cell - char_width) / 2), int(baseline), char)
            cursor += cell
        else:
            char_width = metrics.horizontalAdvance(char)
            painter.drawText(int(cursor), int(baseline), char)
            cursor += char_width + 1
    return cursor - x


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
                background-color: #0A0908;
                color: #F4EDE3;
                border: 1px solid #FF6A00;
                border-radius: 2px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 18px;
                border-radius: 0px;
            }
            QMenu::item:selected {
                background-color: #2A1A0E;
                color: #FF6A00;
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
        theme = dict(THEMES[view.kind])
        level = view.battery
        low = healthy and (
            view.kind == "empty" or (view.kind == "work" and level <= LOW_BATTERY)
        )
        blink = 1.0
        if low:
            blink = 0.28 + 0.72 * (0.5 + 0.5 * math.sin(now * 9.5))
        elif view.kind == "rest" and healthy:
            blink = 0.82 + 0.18 * (0.5 + 0.5 * math.sin(now * 2.6))

        card = QRectF(PAD, PAD, CARD_W, CARD_H)
        self._paint_shadow(painter, card)
        self._paint_panel(painter, card, theme, blink if low else 1.0)
        self._paint_hud(painter, card, theme, view, blink if low else 1.0)

        cell = QRectF(card.x() + 12, card.y() + 16, 20, card.height() - 28)
        self._paint_cells(painter, cell, view, theme, level, blink, now)
        self._paint_copy(painter, card, cell, view, theme, healthy, blink if low else 1.0)

    def _panel_path(self, card: QRectF) -> QPolygonF:
        x, y, w, h = card.x(), card.y(), card.width(), card.height()
        c = CORNER
        return QPolygonF(
            [
                QPointF(x + c, y),
                QPointF(x + w, y),
                QPointF(x + w, y + h - c),
                QPointF(x + w - c, y + h),
                QPointF(x, y + h),
                QPointF(x, y + c),
            ]
        )

    def _paint_shadow(self, painter: QPainter, card: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        layers = 7
        for index in range(layers, 0, -1):
            t = index / layers
            alpha = int(22 * (1 - t) ** 2)
            if alpha <= 0:
                continue
            painter.setBrush(QColor(0, 0, 0, alpha))
            drop = 4 * t
            spread = 3 * t
            rect = card.adjusted(-spread, -spread * 0.2 + drop, spread, spread + drop)
            painter.drawPolygon(self._panel_path(rect))

    def _paint_panel(
        self,
        painter: QPainter,
        card: QRectF,
        theme: dict[str, str],
        blink: float,
    ) -> None:
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        gradient.setColorAt(0, QColor(theme["top"]))
        gradient.setColorAt(1, QColor(theme["bottom"]))
        border = QColor(theme["accent"] if self._bonus > 0 else theme["line"])
        base_alpha = 120 + 135 * self._bonus if self._bonus > 0 else 210
        border.setAlpha(int(base_alpha * blink))
        pen = QPen(border, 1.5 + 1.5 * self._bonus)
        painter.setPen(pen)
        painter.setBrush(gradient)
        painter.drawPolygon(self._panel_path(card))

    def _paint_hud(
        self,
        painter: QPainter,
        card: QRectF,
        theme: dict[str, str],
        view: View,
        blink: float,
    ) -> None:
        line = QColor(theme["line"])
        line.setAlpha(int(150 * blink))
        painter.setPen(QPen(line, 1.0))
        top_y = card.y() + 8
        bot_y = card.bottom() - 8
        painter.drawLine(QPointF(card.x() + CORNER + 2, top_y), QPointF(card.right() - 10, top_y))
        painter.drawLine(QPointF(card.x() + 10, bot_y), QPointF(card.right() - CORNER - 2, bot_y))

        mark = QColor(theme["accent"])
        mark.setAlpha(int(220 * blink))
        painter.setPen(QPen(mark, 1.4))
        painter.drawLine(
            QPointF(card.right() - 18, card.y() + 3),
            QPointF(card.right() - 3, card.y() + 3),
        )
        painter.drawLine(
            QPointF(card.right() - 3, card.y() + 3),
            QPointF(card.right() - 3, card.y() + 14),
        )
        painter.drawLine(
            QPointF(card.x() + 3, card.bottom() - 14),
            QPointF(card.x() + 3, card.bottom() - 3),
        )
        painter.drawLine(
            QPointF(card.x() + 3, card.bottom() - 3),
            QPointF(card.x() + 18, card.bottom() - 3),
        )

        tag = "PWR" if view.kind in {"work", "paused"} else "CHG"
        tag_font = make_font(8, QFont.Weight.Bold)
        painter.setFont(tag_font)
        color = QColor(theme["accent"] if view.kind == "rest" else theme["muted"])
        color.setAlpha(int(255 * blink))
        painter.setPen(color)
        painter.drawText(
            QRectF(card.x() + 10, card.y() + 1, 40, 10),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            tag,
        )

    def _paint_cells(
        self,
        painter: QPainter,
        box: QRectF,
        view: View,
        theme: dict[str, str],
        level: float,
        blink: float,
        now: float,
    ) -> None:
        gap = 2.0
        seg_h = (box.height() - gap * (SEGMENTS - 1)) / SEGMENTS
        lit = level * SEGMENTS
        accent = QColor(theme["accent"])
        track = QColor(theme["track"])

        # 放电：亮段从上往下灭；充电：从下往上点亮。扫描波沿对应方向跑。
        if view.kind == "rest":
            sweep = (now * 0.85) % (SEGMENTS + 2)
        elif view.kind == "work":
            sweep = (SEGMENTS + 2) - ((now * 3.2) % (SEGMENTS + 2))
        else:
            sweep = -1.0

        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(SEGMENTS):
            # index 0 = 底部。
            y = box.bottom() - (index + 1) * seg_h - index * gap
            rect = QRectF(box.x(), y, box.width(), seg_h)
            painter.setBrush(track)
            painter.drawRect(rect)

            fill = max(0.0, min(1.0, lit - index))
            if fill <= 0.001:
                # 充电时空段也有追逐光点。
                if view.kind == "rest" and abs(index + 0.5 - sweep) < 0.85:
                    ghost = QColor(accent)
                    ghost.setAlpha(int(70 * blink))
                    painter.setBrush(ghost)
                    painter.drawRect(rect)
                continue

            color = QColor(accent)
            if view.kind == "paused":
                color.setAlpha(130)
            else:
                boost = 1.0
                if sweep >= 0:
                    dist = abs(index + 0.5 - sweep)
                    if dist < 1.2:
                        boost = 1.0 + 0.55 * (1.0 - dist / 1.2)
                if view.kind == "work":
                    # 放电：顶端交界段额外闪。
                    edge = lit
                    if abs(index + 0.5 - edge) < 0.9:
                        boost *= 0.55 + 0.45 * (0.5 + 0.5 * math.sin(now * 12))
                alpha = int(255 * blink * min(1.35, boost) * (0.35 + 0.65 * fill))
                color.setAlpha(max(40, min(255, alpha)))
            painter.setBrush(color)
            if fill >= 0.999:
                painter.drawRect(rect)
            else:
                painter.drawRect(QRectF(rect.x(), rect.bottom() - rect.height() * fill, rect.width(), rect.height() * fill))

        # 外壳与正极头。
        shell = QColor(theme["line"])
        shell.setAlpha(int(200 * blink))
        painter.setPen(QPen(shell, 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(box.adjusted(-2, -2, 2, 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shell)
        painter.drawRect(QRectF(box.center().x() - 4, box.y() - 5, 8, 3))

    def _paint_copy(
        self,
        painter: QPainter,
        card: QRectF,
        cell: QRectF,
        view: View,
        theme: dict[str, str],
        healthy: bool,
        blink: float,
    ) -> None:
        label, subtitle = copy_for(view)
        if not healthy:
            label, subtitle = "NO SIGNAL", "Restart unit"

        hero_text = format_duration(view.hero_seconds)

        label_font = make_font(10, QFont.Weight.Bold)
        hero_size = 15 if hero_text.count(":") >= 2 else 20
        hero_font = make_font(hero_size, QFont.Weight.DemiBold, digits=True)
        sub_font = make_font(9)

        label_metrics = QFontMetrics(label_font)
        hero_metrics = QFontMetrics(hero_font)
        sub_metrics = QFontMetrics(sub_font)

        text_x = cell.right() + 12
        right = card.right() - 12
        label_x = text_x + 11
        text_w = max(40.0, right - label_x)
        gap_after_label = 1
        gap_after_hero = 2
        block_h = (
            label_metrics.height()
            + gap_after_label
            + hero_metrics.height()
            + gap_after_hero
            + sub_metrics.height()
        )
        y = card.y() + (card.height() - block_h) / 2

        label_w = text_w

        dot_cy = y + label_metrics.height() / 2
        dot_color = QColor("#FF2A2A" if not healthy else theme["dot"])
        painter.setPen(Qt.PenStyle.NoPen)
        outer = QColor(dot_color)
        breath = blink
        if view.kind == "rest" and healthy:
            breath = 0.7 + 0.3 * (0.5 + 0.5 * math.sin(time.monotonic() * 2.4))
        outer.setAlpha(int(90 * breath))
        side = 5.0 * breath
        painter.setBrush(outer)
        painter.drawRect(QRectF(text_x + 3 - side / 2, dot_cy - side / 2, side, side))
        core = QColor(dot_color)
        core.setAlpha(int(255 * blink))
        painter.setBrush(core)
        painter.drawRect(QRectF(text_x + 1.5, dot_cy - 1.6, 3.2, 3.2))

        painter.setFont(label_font)
        label_color = QColor(theme["accent"] if healthy else "#FF8A7A")
        label_color.setAlpha(int(255 * blink))
        painter.setPen(label_color)
        painter.drawText(
            QRectF(label_x, y, max(20, label_w), label_metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        y += label_metrics.height() + gap_after_label
        painter.setFont(hero_font)
        baseline = y + hero_metrics.ascent()
        text_color = QColor(theme["text"])
        text_color.setAlpha(int(255 * blink))
        draw_time(painter, label_x, baseline, hero_text, text_color)
        y += hero_metrics.height() + gap_after_hero

        painter.setFont(sub_font)
        muted = QColor(theme["muted"])
        muted.setAlpha(int(255 * blink))
        painter.setPen(muted)
        shown = painter.fontMetrics().elidedText(subtitle, Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(
            QRectF(label_x, y, text_w, sub_metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            shown,
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
