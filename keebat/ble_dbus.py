"""Read battery levels via BlueZ D-Bus GATT interface.

BlueZ Battery1 only exposes a single battery percentage, but ZMK split
keyboards advertise two BAS instances (UUID 0x180F) — one per half.
We enumerate GATT services/characteristics directly via D-Bus to read both.
"""

from __future__ import annotations

import logging

from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant

from .models import BatteryState

log = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


def _variant_value(val):
    return val.value if isinstance(val, Variant) else val


async def _get_bus() -> MessageBus:
    return await MessageBus(bus_type=BusType.SYSTEM).connect()


async def _find_battery_char_paths(
    bus: MessageBus, device_path: str
) -> list[str]:
    """Find D-Bus paths of all Battery Level characteristics under a device.

    Returns paths sorted by GATT handle (object path order), so the first
    is the central battery and the second is the peripheral battery.
    """
    introspection = await bus.introspect(BLUEZ_SERVICE, "/")
    root_proxy = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
    om = root_proxy.get_interface(OBJECT_MANAGER_IFACE)
    objects: dict = await om.call_get_managed_objects()

    # Collect BAS service paths
    bas_service_paths: list[str] = []
    for path, ifaces in objects.items():
        if not path.startswith(device_path + "/"):
            continue
        if GATT_SERVICE_IFACE in ifaces:
            uuid = _variant_value(ifaces[GATT_SERVICE_IFACE].get("UUID", ""))
            if uuid == BATTERY_SERVICE_UUID:
                bas_service_paths.append(path)

    bas_service_paths.sort()
    log.debug("BAS service paths: %s", bas_service_paths)

    # For each BAS service, find its Battery Level characteristic
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


async def _read_gatt_char(bus: MessageBus, char_path: str) -> int:
    """Read a single GATT characteristic value via D-Bus."""
    introspection = await bus.introspect(BLUEZ_SERVICE, char_path)
    proxy = bus.get_proxy_object(BLUEZ_SERVICE, char_path, introspection)
    char_iface = proxy.get_interface(GATT_CHAR_IFACE)
    # ReadValue expects a dict of options (empty for a simple read)
    data: bytes = await char_iface.call_read_value({})
    return data[0]


async def read_battery_dbus(device_path: str) -> BatteryState:
    """Read battery percentages for both halves via D-Bus GATT.

    Args:
        device_path: D-Bus object path, e.g. /org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX

    Returns:
        BatteryState with central and (if available) peripheral battery.
    """
    bus = await _get_bus()
    try:
        char_paths = await _find_battery_char_paths(bus, device_path)

        if not char_paths:
            log.warning("No Battery Level characteristics found on %s", device_path)
            return BatteryState(connected=True)

        central_pct = await _read_gatt_char(bus, char_paths[0])
        peripheral_pct = None
        if len(char_paths) >= 2:
            peripheral_pct = await _read_gatt_char(bus, char_paths[1])

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


async def watch_battery_dbus(device_path: str, callback):
    """Subscribe to Battery Level notifications via D-Bus GATT.

    Starts notifications on all Battery Level characteristics and calls
    callback(BatteryState) when any value changes.

    Returns:
        A MessageBus that must be disconnected to stop watching, or None.
    """
    bus = await _get_bus()
    try:
        char_paths = await _find_battery_char_paths(bus, device_path)
        if not char_paths:
            bus.disconnect()
            return None

        for char_path in char_paths:
            try:
                introspection = await bus.introspect(BLUEZ_SERVICE, char_path)
                proxy = bus.get_proxy_object(BLUEZ_SERVICE, char_path, introspection)
                props = proxy.get_interface(PROPERTIES_IFACE)

                def _make_handler(dp=device_path, cb=callback, b=bus, paths=char_paths):
                    def on_props_changed(iface_name, changed, invalidated):
                        if iface_name == GATT_CHAR_IFACE and "Value" in changed:
                            import asyncio
                            asyncio.ensure_future(_on_notify(b, paths, cb))
                    return on_props_changed

                props.on_properties_changed(_make_handler())

                char_iface = proxy.get_interface(GATT_CHAR_IFACE)
                await char_iface.call_start_notify()
                log.debug("Started GATT notify on %s", char_path)
            except Exception:
                log.debug("Could not start notify on %s", char_path, exc_info=True)

        return bus
    except Exception:
        bus.disconnect()
        raise


async def _on_notify(bus: MessageBus, char_paths: list[str], callback):
    """Re-read all battery chars and invoke callback."""
    try:
        central_pct = await _read_gatt_char(bus, char_paths[0])
        peripheral_pct = None
        if len(char_paths) >= 2:
            peripheral_pct = await _read_gatt_char(bus, char_paths[1])

        state = BatteryState(
            central_pct=central_pct,
            peripheral_pct=peripheral_pct,
            connected=True,
        )
        callback(state)
    except Exception:
        log.warning("Failed to read battery on notify", exc_info=True)
