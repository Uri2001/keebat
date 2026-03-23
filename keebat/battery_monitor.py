"""Orchestrates battery reading with D-Bus → GATT fallback and reconnection."""

from __future__ import annotations

import asyncio
import logging

from PyQt6.QtCore import QObject, pyqtSignal

from .ble_dbus import read_battery_dbus, watch_battery_dbus
from .ble_gatt import GATTBatteryReader
from .device_discovery import find_device
from .models import BatteryState, DeviceConfig

log = logging.getLogger(__name__)

BACKOFF_BASE = 5
BACKOFF_MAX = 120


class BatteryMonitor(QObject):
    """Monitors battery levels using D-Bus fast path with GATT fallback."""

    battery_updated = pyqtSignal(BatteryState)

    def __init__(self, config: DeviceConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._gatt_reader: GATTBatteryReader | None = None
        self._dbus_watch_bus = None
        self._running = False
        self._backoff = BACKOFF_BASE
        self._device_path: str | None = None
        self._mac_address: str | None = None

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._discover_device()
                await self._connect_and_monitor()
            except asyncio.CancelledError:
                break
            except Exception:
                log.warning("Monitor error, retrying in %ds", self._backoff, exc_info=True)
                self.battery_updated.emit(BatteryState(connected=False))
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, BACKOFF_MAX)

    def stop(self) -> None:
        self._running = False
        if self._dbus_watch_bus:
            self._dbus_watch_bus.disconnect()
            self._dbus_watch_bus = None

    async def _discover_device(self) -> None:
        """Find the device D-Bus path and MAC address."""
        if self._device_path and self._mac_address:
            return

        result = await find_device(
            name=self._config.device_name,
            mac=self._config.mac_address,
        )
        if result is None:
            raise RuntimeError("Device not found")

        self._device_path, self._mac_address = result
        log.info("Found device: path=%s mac=%s", self._device_path, self._mac_address)

    async def _connect_and_monitor(self) -> None:
        """Try D-Bus path first, fall back to GATT, then poll."""
        # Attempt 1: D-Bus Battery1
        state = await self._try_dbus()
        if state and state.central_pct is not None:
            self._backoff = BACKOFF_BASE
            self.battery_updated.emit(state)

            # If we got both batteries from D-Bus, just watch for changes
            if state.peripheral_pct is not None:
                await self._watch_dbus_and_poll()
                return

        # Attempt 2: GATT via bleak (needed for dual battery)
        state = await self._try_gatt()
        if state and state.connected:
            self._backoff = BACKOFF_BASE
            self.battery_updated.emit(state)
            await self._poll_gatt()
            return

        # Nothing worked
        raise RuntimeError("Could not read battery via D-Bus or GATT")

    async def _try_dbus(self) -> BatteryState | None:
        try:
            return await read_battery_dbus(self._device_path)
        except Exception:
            log.debug("D-Bus battery read failed", exc_info=True)
            return None

    async def _try_gatt(self) -> BatteryState | None:
        if not self._mac_address:
            return None
        try:
            self._gatt_reader = GATTBatteryReader(self._mac_address)
            await self._gatt_reader.connect()
            state = await self._gatt_reader.read_batteries()
            # Try to subscribe for notifications
            await self._gatt_reader.subscribe(
                lambda s: self.battery_updated.emit(s)
            )
            return state
        except Exception:
            log.debug("GATT battery read failed", exc_info=True)
            if self._gatt_reader:
                await self._gatt_reader.disconnect()
                self._gatt_reader = None
            return None

    async def _watch_dbus_and_poll(self) -> None:
        """Watch D-Bus for changes and poll as fallback."""
        self._dbus_watch_bus = await watch_battery_dbus(
            self._device_path,
            lambda state: self.battery_updated.emit(state),
        )
        # Also poll periodically in case signals are missed
        await self._poll_dbus()

    async def _poll_dbus(self) -> None:
        while self._running:
            await asyncio.sleep(self._config.poll_interval)
            if not self._running:
                break
            state = await self._try_dbus()
            if state and state.central_pct is not None:
                self.battery_updated.emit(state)
            else:
                # Device disconnected, break to trigger reconnect
                self._device_path = None
                self._mac_address = None
                break

    async def _poll_gatt(self) -> None:
        while self._running:
            await asyncio.sleep(self._config.poll_interval)
            if not self._running:
                break
            if not self._gatt_reader or not self._gatt_reader.is_connected:
                # Disconnected, break to trigger reconnect
                self._device_path = None
                self._mac_address = None
                break
            try:
                state = await self._gatt_reader.read_batteries()
                self.battery_updated.emit(state)
            except Exception:
                log.debug("GATT poll failed", exc_info=True)
                break

    async def refresh(self) -> None:
        """Force an immediate battery read."""
        state = await self._try_dbus()
        if state and state.central_pct is not None:
            self.battery_updated.emit(state)
            return
        if self._gatt_reader and self._gatt_reader.is_connected:
            state = await self._gatt_reader.read_batteries()
            self.battery_updated.emit(state)
