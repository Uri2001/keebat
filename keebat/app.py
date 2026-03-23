"""Application bootstrap: runs asyncio in a QThread, Qt in the main thread."""

from __future__ import annotations

import logging
import signal
import sys

from PyQt6.QtWidgets import QApplication

from .battery_monitor import BatteryMonitor
from .config import load_config
from .tray import TrayIcon

log = logging.getLogger(__name__)


def run() -> int:
    config = load_config()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    if not config.device_name and not config.mac_address:
        log.error(
            "No device configured. Edit ~/.config/keebat/keebat.toml "
            "and set device.name or device.mac"
        )
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("keebat")
    app.setQuitOnLastWindowClosed(False)

    # Let SIGINT (Ctrl+C) and SIGTERM quit the Qt event loop gracefully
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())

    tray = TrayIcon(config)
    monitor = BatteryMonitor(config)

    monitor.battery_updated.connect(tray.update_battery)
    tray.set_refresh_callback(monitor.request_refresh)

    monitor.start()

    ret = app.exec()

    monitor.stop_monitor()
    monitor.wait()
    return ret
