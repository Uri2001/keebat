"""Dynamic battery icon rendering for the system tray."""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

from .models import BatteryState

ICON_SIZE = 64
BAR_WIDTH = 22
BAR_HEIGHT = 48
BAR_GAP = 6
TIP_HEIGHT = 4
TIP_WIDTH = 10
BORDER = 2
CORNER_RADIUS = 3


def _battery_color(pct: int | None, threshold: int) -> QColor:
    if pct is None:
        return QColor(128, 128, 128)  # gray
    if pct <= threshold:
        return QColor(220, 50, 50)  # red
    if pct <= 40:
        return QColor(230, 180, 30)  # yellow
    return QColor(70, 180, 70)  # green


def _draw_battery(
    painter: QPainter, x: int, pct: int | None, threshold: int
) -> None:
    """Draw a single battery bar at the given x offset."""
    y_base = (ICON_SIZE - BAR_HEIGHT - TIP_HEIGHT) // 2 + TIP_HEIGHT

    # Battery tip (positive terminal)
    tip_x = x + (BAR_WIDTH - TIP_WIDTH) // 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(180, 180, 180))
    painter.drawRoundedRect(
        QRect(tip_x, y_base - TIP_HEIGHT, TIP_WIDTH, TIP_HEIGHT + 2),
        1, 1,
    )

    # Battery outline
    painter.setBrush(QColor(60, 60, 60))
    painter.drawRoundedRect(
        QRect(x, y_base, BAR_WIDTH, BAR_HEIGHT),
        CORNER_RADIUS, CORNER_RADIUS,
    )

    # Battery inner background
    inner = QRect(
        x + BORDER, y_base + BORDER,
        BAR_WIDTH - 2 * BORDER, BAR_HEIGHT - 2 * BORDER,
    )
    painter.setBrush(QColor(30, 30, 30))
    painter.drawRoundedRect(inner, 2, 2)

    # Fill level
    if pct is not None:
        fill_height = int(inner.height() * pct / 100)
        fill_rect = QRect(
            inner.x(), inner.y() + inner.height() - fill_height,
            inner.width(), fill_height,
        )
        painter.setBrush(_battery_color(pct, threshold))
        painter.drawRoundedRect(fill_rect, 1, 1)
    else:
        # Draw "?" for unknown
        painter.setPen(QColor(128, 128, 128))
        font = painter.font()
        font.setPixelSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "?")
        painter.setPen(Qt.PenStyle.NoPen)


def render_icon(state: BatteryState, threshold: int = 20) -> QIcon:
    """Render a split battery tray icon showing both halves."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Two battery bars side by side
    total_width = 2 * BAR_WIDTH + BAR_GAP
    x_start = (ICON_SIZE - total_width) // 2

    _draw_battery(painter, x_start, state.central_pct, threshold)
    _draw_battery(painter, x_start + BAR_WIDTH + BAR_GAP, state.peripheral_pct, threshold)

    painter.end()
    return QIcon(pixmap)


def render_disconnected_icon() -> QIcon:
    """Render a grayed-out icon for disconnected state."""
    return render_icon(BatteryState(connected=False), threshold=20)
