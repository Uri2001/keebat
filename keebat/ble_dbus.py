"""Read battery levels via BlueZ D-Bus GATT interface.

BlueZ Battery1 only exposes a single battery percentage, but ZMK split
keyboards advertise two BAS instances (UUID 0x180F) — one per half.
We enumerate GATT services/characteristics directly via D-Bus to read both.

Characteristic paths are discovered once and cached; each read uses a
fresh D-Bus connection to avoid stale proxy issues.
"""

from __future__ import annotations

import asyncio
import logging

from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant

from .models import BatteryState

log = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

READ_TIMEOUT = 10  # seconds


def _variant_value(val):
    return val.value if isinstance(val, Variant) else val


async def discover_battery_chars(device_path: str) -> list[str]:
    """Find D-Bus object paths of all Battery Level characteristics.

    Connects to D-Bus, calls GetManagedObjects once, then disconnects.
    Returns paths sorted by GATT handle order (first = central, second = peripheral).
    """
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        introspection = await bus.introspect(BLUEZ_SERVICE, "/")
        root_proxy = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        om = root_proxy.get_interface(OBJECT_MANAGER_IFACE)
        objects: dict = await om.call_get_managed_objects()

        bas_service_paths: list[str] = sorted(
            path for path, ifaces in objects.items()
            if path.startswith(device_path + "/")
            and GATT_SERVICE_IFACE in ifaces
            and _variant_value(ifaces[GATT_SERVICE_IFACE].get("UUID", ""))
            == BATTERY_SERVICE_UUID
        )
        log.debug("BAS service paths: %s", bas_service_paths)

        char_paths: list[str] = []
        for svc_path in bas_service_paths:
            for path, ifaces in objects.items():
                if not path.startswith(svc_path + "/"):
                    continue
                if GATT_CHAR_IFACE in ifaces:
                    uuid = _variant_value(ifaces[GATT_CHAR_IFACE].get("UUID", ""))
                    if uuid == BATTERY_LEVEL_UUID:
                        char_paths.append(path)

        char_paths.sort()
        log.debug("Battery Level characteristic paths: %s", char_paths)
        return char_paths
    finally:
        bus.disconnect()


async def read_battery_chars(char_paths: list[str]) -> BatteryState:
    """Read battery percentages from cached characteristic paths.

    Opens a fresh D-Bus connection, reads values, then disconnects.
    """
    if not char_paths:
        return BatteryState(connected=True)

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        central_pct = await _read_char(bus, char_paths[0])
        peripheral_pct = None
        if len(char_paths) >= 2:
            peripheral_pct = await _read_char(bus, char_paths[1])

        log.debug(
            "Battery read: central=%s%% peripheral=%s%%",
            central_pct, peripheral_pct,
        )
        return BatteryState(
            central_pct=central_pct,
            peripheral_pct=peripheral_pct,
            connected=True,
        )
    finally:
        bus.disconnect()


async def _read_char(bus: MessageBus, char_path: str) -> int:
    """Read a single GATT characteristic via D-Bus with timeout."""
    introspection = await bus.introspect(BLUEZ_SERVICE, char_path)
    proxy = bus.get_proxy_object(BLUEZ_SERVICE, char_path, introspection)
    char_iface = proxy.get_interface(GATT_CHAR_IFACE)
    data: bytes = await asyncio.wait_for(
        char_iface.call_read_value({}), timeout=READ_TIMEOUT
    )
    return data[0]
