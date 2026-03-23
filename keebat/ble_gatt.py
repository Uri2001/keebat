"""Read battery levels via direct GATT access using bleak.

This is the fallback path when D-Bus Battery1 doesn't expose both batteries.
ZMK with split battery proxy advertises two BAS instances (UUID 0x180F),
each containing a Battery Level characteristic (UUID 0x2A19).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .models import BatteryState

log = logging.getLogger(__name__)

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


class GATTBatteryReader:
    """Reads battery levels from multiple BAS instances via GATT."""

    def __init__(self, address: str):
        self._address = address
        self._client: BleakClient | None = None
        self._on_update: Callable[[BatteryState], None] | None = None
        self._central_handle: int | None = None
        self._peripheral_handle: int | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self) -> None:
        self._client = BleakClient(
            self._address,
            disconnected_callback=self._on_disconnect,
        )
        await self._client.connect()
        self._discover_battery_characteristics()
        log.info(
            "GATT connected to %s — central handle: %s, peripheral handle: %s",
            self._address, self._central_handle, self._peripheral_handle,
        )

    def _discover_battery_characteristics(self) -> None:
        """Find all Battery Level characteristics, sorted by handle."""
        chars: list[BleakGATTCharacteristic] = []
        for service in self._client.services:
            if service.uuid == BATTERY_SERVICE_UUID:
                for char in service.characteristics:
                    if char.uuid == BATTERY_LEVEL_UUID:
                        chars.append(char)

        chars.sort(key=lambda c: c.handle)

        if len(chars) >= 1:
            self._central_handle = chars[0].handle
        if len(chars) >= 2:
            self._peripheral_handle = chars[1].handle

        if not chars:
            log.warning("No Battery Level characteristics found on %s", self._address)

    async def read_batteries(self) -> BatteryState:
        if not self.is_connected:
            return BatteryState(connected=False)

        central_pct = None
        peripheral_pct = None

        if self._central_handle is not None:
            data = await self._client.read_gatt_char(self._central_handle)
            central_pct = data[0]

        if self._peripheral_handle is not None:
            data = await self._client.read_gatt_char(self._peripheral_handle)
            peripheral_pct = data[0]

        return BatteryState(
            central_pct=central_pct,
            peripheral_pct=peripheral_pct,
            connected=True,
        )

    async def subscribe(self, callback: Callable[[BatteryState], None]) -> None:
        """Subscribe to battery level notifications on both characteristics."""
        self._on_update = callback

        if self._central_handle is not None:
            try:
                await self._client.start_notify(
                    self._central_handle, self._make_handler("central")
                )
            except Exception:
                log.debug("Central battery notify not supported, will poll", exc_info=True)

        if self._peripheral_handle is not None:
            try:
                await self._client.start_notify(
                    self._peripheral_handle, self._make_handler("peripheral")
                )
            except Exception:
                log.debug("Peripheral battery notify not supported, will poll", exc_info=True)

    def _make_handler(self, which: str):
        def handler(_char: BleakGATTCharacteristic, data: bytearray):
            if self._on_update is None:
                return
            pct = data[0]
            log.debug("BLE notify: %s battery = %d%%", which, pct)
            # Read full state and notify
            asyncio.ensure_future(self._read_and_notify())
        return handler

    async def _read_and_notify(self) -> None:
        try:
            state = await self.read_batteries()
            if self._on_update:
                self._on_update(state)
        except Exception:
            log.warning("Failed to read batteries after notify", exc_info=True)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._central_handle = None
        self._peripheral_handle = None

    def _on_disconnect(self, _client: BleakClient) -> None:
        log.info("GATT disconnected from %s", self._address)
        if self._on_update:
            self._on_update(BatteryState(connected=False))
