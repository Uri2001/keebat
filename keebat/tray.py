"""System tray icon for KDE Plasma."""

from __future__ import annotations

import asyncio
import logging

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

from .icons import render_disconnected_icon, render_icon
from .models import BatteryState, DeviceConfig

log = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, config: DeviceConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._state = BatteryState()
        self._refresh_callback = None

        self.setIcon(render_disconnected_icon())
        self.setToolTip("keebat: searching for keyboard...")

        self._build_menu()
        self.show()

    def set_refresh_callback(self, callback) -> None:
        self._refresh_callback = callback

    def _build_menu(self) -> None:
        menu = QMenu()

        refresh_action = QAction("Refresh", menu)
        refresh_action.triggered.connect(self._on_refresh)
        menu.addAction(refresh_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_refresh(self) -> None:
        if self._refresh_callback:
            asyncio.ensure_future(self._refresh_callback())

    def update_battery(self, state: BatteryState) -> None:
        self._state = state

        if not state.connected:
            self.setIcon(render_disconnected_icon())
            self.setToolTip("keebat: keyboard disconnected")
            return

        self.setIcon(render_icon(state, self._config.low_battery_threshold))
        self.setToolTip(self._format_tooltip(state))

        if self._config.notify_low_battery:
            self._check_low_battery(state)

    def _format_tooltip(self, state: BatteryState) -> str:
        c_label = self._config.central_label
        p_label = self._config.peripheral_label
        c_pct = f"{state.central_pct}%" if state.central_pct is not None else "N/A"
        p_pct = f"{state.peripheral_pct}%" if state.peripheral_pct is not None else "N/A"
        return f"keebat\n{c_label}: {c_pct}\n{p_label}: {p_pct}"

    def _check_low_battery(self, state: BatteryState) -> None:
        threshold = self._config.low_battery_threshold
        for label, pct in [
            (self._config.central_label, state.central_pct),
            (self._config.peripheral_label, state.peripheral_pct),
        ]:
            if pct is not None and pct <= threshold:
                self.showMessage(
                    "keebat — Low Battery",
                    f"{label} half: {pct}%",
                    QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )
