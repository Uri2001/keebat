from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BatteryState:
    central_pct: int | None = None
    peripheral_pct: int | None = None
    connected: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DeviceConfig:
    device_name: str | None = None
    mac_address: str | None = None
    poll_interval: int = 60
    central_label: str = "Left"
    peripheral_label: str = "Right"
    low_battery_threshold: int = 20
    notify_low_battery: bool = True
    log_level: str = "WARNING"
