from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from .models import DeviceConfig

log = logging.getLogger(__name__)

DEFAULT_CONFIG = """\
[device]
# Identify keyboard by name or MAC address (at least one required)
# name = "My Keyboard"
# mac = "AA:BB:CC:DD:EE:FF"

[battery]
poll_interval = 60
central_label = "Left"
peripheral_label = "Right"

[ui]
low_battery_threshold = 20
notify_low_battery = true

[logging]
# Log level: DEBUG, INFO, WARNING, ERROR
level = "WARNING"
"""


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "keebat"


def _config_path() -> Path:
    return _config_dir() / "keebat.toml"


def load_config() -> DeviceConfig:
    path = _config_path()
    if not path.exists():
        log.info("No config found, creating default at %s", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG)
        return DeviceConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    dev = data.get("device", {})
    bat = data.get("battery", {})
    ui = data.get("ui", {})
    log_section = data.get("logging", {})

    return DeviceConfig(
        device_name=dev.get("name"),
        mac_address=dev.get("mac"),
        poll_interval=bat.get("poll_interval", 60),
        central_label=bat.get("central_label", "Left"),
        peripheral_label=bat.get("peripheral_label", "Right"),
        low_battery_threshold=ui.get("low_battery_threshold", 20),
        notify_low_battery=ui.get("notify_low_battery", True),
        log_level=log_section.get("level", "WARNING"),
    )
