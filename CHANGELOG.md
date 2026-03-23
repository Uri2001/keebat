# Changelog

## Unreleased

### Fixed
- Battery levels now update automatically via persistent D-Bus connection
  with cached GATT characteristic paths (no more re-connecting per poll).
- Graceful shutdown on Ctrl+C / SIGTERM instead of KeyboardInterrupt crash.

### Changed
- `ble_dbus.py` rewritten as `DBusBatteryReader` class with persistent
  connection and pre-introspected interfaces.

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
