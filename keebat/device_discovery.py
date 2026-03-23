"""Discover ZMK keyboard device via BlueZ D-Bus."""

from __future__ import annotations

import fnmatch
import logging

from dbus_fast.aio import MessageBus
from dbus_fast import BusType

log = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
DEVICE_IFACE = "org.bluez.Device1"


async def find_device(
    name: str | None = None,
    mac: str | None = None,
) -> tuple[str, str] | None:
    """Find a BlueZ device by name pattern or MAC address.

    Args:
        name: Device name or glob pattern (e.g. "My Keyboard*").
        mac: Bluetooth MAC address (e.g. "AA:BB:CC:DD:EE:FF").

    Returns:
        Tuple of (dbus_object_path, mac_address) or None if not found.
    """
    if not name and not mac:
        log.error("Either device name or MAC address must be specified")
        return None

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        introspection = await bus.introspect(BLUEZ_SERVICE, "/")
        proxy = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        om = proxy.get_interface(OBJECT_MANAGER_IFACE)
        objects: dict = await om.call_get_managed_objects()

        for path, ifaces in objects.items():
            if DEVICE_IFACE not in ifaces:
                continue

            props = ifaces[DEVICE_IFACE]
            dev_address = _variant_value(props.get("Address", ""))
            dev_name = _variant_value(props.get("Name", ""))
            dev_connected = _variant_value(props.get("Connected", False))

            if not dev_connected:
                continue

            if mac and dev_address.upper() == mac.upper():
                return path, dev_address

            if name and dev_name and fnmatch.fnmatch(dev_name, name):
                return path, dev_address

        log.debug("Device not found (name=%s, mac=%s)", name, mac)
        return None
    finally:
        bus.disconnect()


def _variant_value(val):
    """Extract value from D-Bus Variant if needed."""
    from dbus_fast import Variant
    return val.value if isinstance(val, Variant) else val
