# Changelog

## Unreleased

### Fixed
- Battery levels now update on each poll cycle — char paths are discovered
  once, then each poll opens a fresh D-Bus connection for a reliable read.
- Graceful shutdown on Ctrl+C / SIGTERM: stop event wakes sleeping coroutines
  so the asyncio loop exits cleanly (no more KeyboardInterrupt / core dump).

### Changed
- `ble_dbus.py` simplified to two functions: `discover_battery_chars` (once)
  and `read_battery_chars` (per poll, fresh connection with read timeout).
- Tooltip header now shows the device name instead of "keebat".

## 0.1.0

### Added
- Initial release: system tray battery monitor for ZMK split keyboards.
- Reads both battery halves via D-Bus GATT (primary) or bleak (fallback).
- Two-bar tray icon with color coding (green/yellow/red).
- Desktop notifications on low battery.
- Auto-reconnect with exponential backoff.
- Configurable log level via `[logging] level` in config.
- Device discovery by name (glob patterns) or MAC address.
- XDG config at `~/.config/keebat/keebat.toml`.
