"""Application bootstrap: bridges asyncio and Qt event loops."""

from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PyQt6.QtWidgets import QApplication

from .battery_monitor import BatteryMonitor
from .config import load_config
from .tray import TrayIcon

log = logging.getLogger(__name__)


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    config = load_config()
    if not config.device_name and not config.mac_address:
        log.error(
            "No device configured. Edit ~/.config/keebat/keebat.toml "
            "and set device.name or device.mac"
        )
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("keebat")
    app.setQuitOnLastWindowClosed(False)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    monitor = BatteryMonitor(config)
    tray = TrayIcon(config)

    monitor.battery_updated.connect(tray.update_battery)
    tray.set_refresh_callback(monitor.refresh)

    with loop:
        loop.create_task(monitor.start())
        loop.run_forever()

    monitor.stop()
    return 0
