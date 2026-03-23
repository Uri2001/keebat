"""Orchestrates battery reading with D-Bus -> GATT fallback and reconnection.

Runs an asyncio event loop in a QThread so that dbus-fast and bleak
do not conflict with Qt's main thread.
"""

from __future__ import annotations

import asyncio
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from .ble_dbus import discover_battery_chars, read_battery_chars
from .ble_gatt import GATTBatteryReader
from .device_discovery import find_device
from .models import BatteryState, DeviceConfig

log = logging.getLogger(__name__)

BACKOFF_BASE = 5
BACKOFF_MAX = 120


class BatteryMonitor(QThread):
    """Monitors battery levels in a background thread with its own asyncio loop."""

    battery_updated = pyqtSignal(BatteryState)

    def __init__(self, config: DeviceConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._gatt_reader: GATTBatteryReader | None = None
        self._running = False
        self._backoff = BACKOFF_BASE
        self._device_path: str | None = None
        self._mac_address: str | None = None
        self._char_paths: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._refresh_event: asyncio.Event | None = None

    def run(self) -> None:
        """QThread entry point — creates and runs an asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        self._refresh_event = asyncio.Event()
        self._running = True
        try:
            self._loop.run_until_complete(self._monitor_loop())
        except RuntimeError:
            pass  # "Event loop stopped" on forced shutdown — harmless
        finally:
            self._loop.close()

    def stop_monitor(self) -> None:
        """Thread-safe: signal the monitor loop to exit."""
        self._running = False
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
            self._loop.call_soon_threadsafe(self._refresh_event.set)

    def request_refresh(self) -> None:
        """Thread-safe: request an immediate battery read from the Qt thread."""
        if self._loop and self._refresh_event:
            self._loop.call_soon_threadsafe(self._refresh_event.set)

    async def _wait(self, seconds: float) -> None:
        """Sleep that can be interrupted by stop_monitor or request_refresh."""
        self._refresh_event.clear()
        try:
            await asyncio.wait_for(self._refresh_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                await self._discover_device()
                await self._connect_and_poll()
            except asyncio.CancelledError:
                break
            except Exception:
                if not self._running:
                    break
                log.warning("Monitor error, retrying in %ds", self._backoff, exc_info=True)
                self.battery_updated.emit(BatteryState(connected=False))
                await self._wait(self._backoff)
                self._backoff = min(self._backoff * 2, BACKOFF_MAX)

    async def _discover_device(self) -> None:
        if self._device_path and self._mac_address:
            return

        log.info(
            "Searching for device (name=%s, mac=%s)...",
            self._config.device_name, self._config.mac_address,
        )
        result = await find_device(
            name=self._config.device_name,
            mac=self._config.mac_address,
        )
        if result is None:
            raise RuntimeError(
                f"Device not found: name={self._config.device_name!r}, "
                f"mac={self._config.mac_address!r}"
            )

        self._device_path, self._mac_address = result
        log.info("Found device: path=%s mac=%s", self._device_path, self._mac_address)

    async def _connect_and_poll(self) -> None:
        # Attempt 1: discover GATT chars and read via D-Bus
        if await self._try_dbus_discover():
            state = await self._try_dbus_read()
            if state and state.central_pct is not None:
                self._backoff = BACKOFF_BASE
                self.battery_updated.emit(state)
                await self._poll_dbus()
                return

        # Attempt 2: GATT via bleak (fallback)
        state = await self._try_gatt()
        if state and state.connected:
            self._backoff = BACKOFF_BASE
            self.battery_updated.emit(state)
            await self._poll_gatt()
            return

        raise RuntimeError("Could not read battery via D-Bus or GATT")

    async def _try_dbus_discover(self) -> bool:
        """Discover battery characteristic paths. Returns True if found."""
        try:
            self._char_paths = await discover_battery_chars(self._device_path)
            if self._char_paths:
                log.info("Found %d battery characteristic(s)", len(self._char_paths))
                return True
            return False
        except Exception:
            log.debug("D-Bus discovery failed", exc_info=True)
            return False

    async def _try_dbus_read(self) -> BatteryState | None:
        """Read battery via D-Bus using cached char paths."""
        try:
            state = await read_battery_chars(self._char_paths)
            log.debug("D-Bus read: central=%s peripheral=%s",
                       state.central_pct, state.peripheral_pct)
            return state
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
            await self._gatt_reader.subscribe(
                lambda s: self.battery_updated.emit(s)
            )
            log.debug("GATT read: central=%s peripheral=%s",
                       state.central_pct, state.peripheral_pct)
            return state
        except Exception:
            log.debug("GATT battery read failed", exc_info=True)
            if self._gatt_reader:
                await self._gatt_reader.disconnect()
                self._gatt_reader = None
            return None

    async def _poll_dbus(self) -> None:
        """Poll battery levels, opening a fresh D-Bus connection each time."""
        while self._running:
            await self._wait(self._config.poll_interval)

            if not self._running:
                break

            state = await self._try_dbus_read()
            if state and state.central_pct is not None:
                self.battery_updated.emit(state)
            else:
                log.info("D-Bus read failed during poll, will reconnect")
                self._device_path = None
                self._mac_address = None
                self._char_paths = []
                break

    async def _poll_gatt(self) -> None:
        while self._running:
            await self._wait(self._config.poll_interval)

            if not self._running:
                break
            if not self._gatt_reader or not self._gatt_reader.is_connected:
                self._device_path = None
                self._mac_address = None
                break
            try:
                state = await self._gatt_reader.read_batteries()
                self.battery_updated.emit(state)
            except Exception:
                log.debug("GATT poll failed", exc_info=True)
                break
