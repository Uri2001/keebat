"""Read battery levels via BlueZ D-Bus GATT interface.

BlueZ Battery1 only exposes a single battery percentage, but ZMK split
keyboards advertise two BAS instances (UUID 0x180F) — one per half.
We enumerate GATT services/characteristics directly via D-Bus to read both.

Uses a persistent D-Bus connection with cached characteristic paths to
avoid re-introspecting on every poll.
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


class DBusBatteryReader:
    """Persistent D-Bus connection for reading battery GATT characteristics."""

    def __init__(self):
        self._bus: MessageBus | None = None
        self._char_paths: list[str] = []
        # Cache introspected proxies to avoid re-introspecting on every read
        self._char_ifaces: dict[str, object] = {}

    async def connect(self, device_path: str) -> None:
        """Connect to D-Bus and discover battery characteristic paths."""
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._char_paths = await self._find_battery_char_paths(device_path)
        # Pre-introspect all characteristic interfaces
        for char_path in self._char_paths:
            introspection = await self._bus.introspect(BLUEZ_SERVICE, char_path)
            proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, char_path, introspection)
            self._char_ifaces[char_path] = proxy.get_interface(GATT_CHAR_IFACE)
        log.info(
            "D-Bus GATT connected: %d battery characteristic(s) found",
            len(self._char_paths),
        )

    async def read_batteries(self) -> BatteryState:
        """Read battery percentages using cached interfaces."""
        if not self._bus or not self._char_paths:
            return BatteryState(connected=False)

        central_pct = await self._read_char(self._char_paths[0])
        peripheral_pct = None
        if len(self._char_paths) >= 2:
            peripheral_pct = await self._read_char(self._char_paths[1])

        log.debug(
            "Battery read: central=%s%% peripheral=%s%%",
            central_pct, peripheral_pct,
        )
        return BatteryState(
            central_pct=central_pct,
            peripheral_pct=peripheral_pct,
            connected=True,
        )

    async def start_notify(self, callback) -> None:
        """Subscribe to GATT notifications on battery characteristics."""
        if not self._bus or not self._char_paths:
            return

        for char_path in self._char_paths:
            try:
                introspection = await self._bus.introspect(BLUEZ_SERVICE, char_path)
                proxy = self._bus.get_proxy_object(
                    BLUEZ_SERVICE, char_path, introspection
                )
                props = proxy.get_interface(PROPERTIES_IFACE)

                def _make_handler(cb=callback):
                    def on_props_changed(iface_name, changed, _invalidated):
                        if iface_name == GATT_CHAR_IFACE and "Value" in changed:
                            import asyncio
                            asyncio.ensure_future(self._notify(cb))
                    return on_props_changed

                props.on_properties_changed(_make_handler())

                char_iface = proxy.get_interface(GATT_CHAR_IFACE)
                await char_iface.call_start_notify()
                log.debug("Started GATT notify on %s", char_path)
            except Exception:
                log.debug("Could not start notify on %s", char_path, exc_info=True)

    def disconnect(self) -> None:
        """Disconnect the D-Bus bus."""
        if self._bus:
            self._bus.disconnect()
            self._bus = None
        self._char_paths = []
        self._char_ifaces = {}

    @property
    def is_connected(self) -> bool:
        return self._bus is not None and self._bus.connected

    @property
    def has_peripheral(self) -> bool:
        return len(self._char_paths) >= 2

    async def _read_char(self, char_path: str) -> int:
        iface = self._char_ifaces[char_path]
        data: bytes = await iface.call_read_value({})
        return data[0]

    async def _find_battery_char_paths(self, device_path: str) -> list[str]:
        introspection = await self._bus.introspect(BLUEZ_SERVICE, "/")
        root_proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        om = root_proxy.get_interface(OBJECT_MANAGER_IFACE)
        objects: dict = await om.call_get_managed_objects()

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

    async def _notify(self, callback) -> None:
        try:
            state = await self.read_batteries()
            callback(state)
        except Exception:
            log.warning("Failed to read battery on notify", exc_info=True)
