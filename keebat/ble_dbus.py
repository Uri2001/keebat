"""Read battery levels from BlueZ org.bluez.Battery1 D-Bus interface."""

from __future__ import annotations

import logging

from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant

from .models import BatteryState

log = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
BATTERY_IFACE = "org.bluez.Battery1"
DEVICE_IFACE = "org.bluez.Device1"


async def _get_bus() -> MessageBus:
    return await MessageBus(bus_type=BusType.SYSTEM).connect()


async def read_battery_dbus(device_path: str) -> BatteryState:
    """Read battery percentage(s) from Battery1 interface on a BlueZ device.

    BlueZ may expose one or two Battery1 interfaces depending on the number
    of BAS instances advertised by the device.

    Args:
        device_path: D-Bus object path, e.g. /org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF

    Returns:
        BatteryState with available battery percentages.
    """
    bus = await _get_bus()
    try:
        return await _read_batteries(bus, device_path)
    finally:
        bus.disconnect()


async def _read_batteries(bus: MessageBus, device_path: str) -> BatteryState:
    introspection = await bus.introspect(BLUEZ_SERVICE, device_path)
    proxy = bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)

    # Check if Battery1 interface exists on the device
    iface_names = [iface.name for iface in introspection.interfaces]
    if BATTERY_IFACE not in iface_names:
        log.debug("No Battery1 interface on %s", device_path)
        return BatteryState(connected=True)

    props = proxy.get_interface(PROPERTIES_IFACE)
    percentage = await props.call_get(BATTERY_IFACE, "Percentage")
    central_pct = percentage.value if isinstance(percentage, Variant) else percentage

    # BlueZ may also expose battery on sub-paths for multi-BAS devices.
    # Check for a second Battery1 at device_path/battery1 or similar.
    peripheral_pct = await _try_read_sub_battery(bus, device_path)

    return BatteryState(
        central_pct=int(central_pct),
        peripheral_pct=int(peripheral_pct) if peripheral_pct is not None else None,
        connected=True,
    )


async def _try_read_sub_battery(bus: MessageBus, device_path: str) -> int | None:
    """Try to find a second Battery1 interface under the device's object tree.

    Some BlueZ versions expose multiple Battery1 objects for multi-BAS devices.
    """
    try:
        introspection = await bus.introspect(BLUEZ_SERVICE, "/")
        root_proxy = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        om = root_proxy.get_interface(OBJECT_MANAGER_IFACE)
        objects: dict = await om.call_get_managed_objects()

        battery_paths = sorted(
            path for path, ifaces in objects.items()
            if path.startswith(device_path + "/") and BATTERY_IFACE in ifaces
        )

        if not battery_paths:
            return None

        # Read the first sub-battery (peripheral)
        path = battery_paths[0]
        sub_intro = await bus.introspect(BLUEZ_SERVICE, path)
        sub_proxy = bus.get_proxy_object(BLUEZ_SERVICE, path, sub_intro)
        props = sub_proxy.get_interface(PROPERTIES_IFACE)
        val = await props.call_get(BATTERY_IFACE, "Percentage")
        return val.value if isinstance(val, Variant) else val
    except Exception:
        log.debug("No sub-battery found under %s", device_path, exc_info=True)
        return None


async def watch_battery_dbus(device_path: str, callback):
    """Subscribe to Battery1 PropertiesChanged signals.

    Args:
        device_path: D-Bus object path of the device.
        callback: async callable(BatteryState) invoked on change.

    Returns:
        A MessageBus that must be disconnected to stop watching.
    """
    bus = await _get_bus()
    introspection = await bus.introspect(BLUEZ_SERVICE, device_path)
    proxy = bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)

    iface_names = [iface.name for iface in introspection.interfaces]
    if PROPERTIES_IFACE not in iface_names:
        bus.disconnect()
        return None

    props = proxy.get_interface(PROPERTIES_IFACE)

    def on_props_changed(iface_name: str, changed: dict, invalidated: list):
        if iface_name == BATTERY_IFACE and "Percentage" in changed:
            import asyncio
            asyncio.ensure_future(_notify(bus, device_path, callback))

    props.on_properties_changed(on_props_changed)
    return bus


async def _notify(bus: MessageBus, device_path: str, callback):
    try:
        state = await _read_batteries(bus, device_path)
        await callback(state)
    except Exception:
        log.warning("Failed to read battery on change", exc_info=True)
