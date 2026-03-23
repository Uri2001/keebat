# keebat

ZMK split keyboard battery monitor — system tray app for Linux/KDE Plasma.

## Project overview

- **Language:** Python 3.11+
- **Dependencies:** PyQt6, bleak, dbus-fast
- **Build system:** Hatchling (`pyproject.toml`)
- **Entry point:** `keebat/__main__.py` → `keebat/app.py:run()`
- **Target platform:** Linux with BlueZ 5.55+, KDE Plasma
- **Remote:** https://github.com/Uri2001/keebat

## Architecture

### Threading model

- **Main thread:** Qt event loop (`QApplication.exec()`)
- **Background QThread:** owns its own `asyncio.new_event_loop()` for dbus-fast and bleak
- Cross-thread communication via `pyqtSignal`
- **Do NOT use qasync** — it causes `QSocketNotifier`/`QTimer` thread warnings with dbus-fast

### Battery reading strategy

1. **D-Bus GATT (primary):** `discover_battery_chars()` enumerates BLE Battery Service instances (UUID `0x180F`) via BlueZ `ObjectManager` once at startup and caches characteristic paths. `read_battery_chars()` opens a fresh D-Bus connection per poll, reads `0x2A19` with a 10s timeout, then disconnects. First char = central, second = peripheral.
2. **bleak (fallback):** direct GATT connection, same logic but via bleak client.
3. **Do NOT rely on `org.bluez.Battery1`** — it only exposes a single battery percentage.
4. **Do NOT hold persistent dbus-fast connections** — they go stale silently. Use fresh connection per read.

### Key modules

| Module | Responsibility |
|---|---|
| `app.py` | Bootstrap, wires Qt + monitor + tray |
| `battery_monitor.py` | QThread orchestrator, fallback chain, reconnection |
| `ble_dbus.py` | D-Bus GATT reads for both BAS instances |
| `ble_gatt.py` | bleak-based GATT fallback |
| `device_discovery.py` | Find device by name/MAC via BlueZ D-Bus |
| `tray.py` | QSystemTrayIcon, tooltip, context menu |
| `icons.py` | Dynamic split battery icon rendering |
| `config.py` | TOML config from `~/.config/keebat/keebat.toml` |
| `models.py` | `BatteryState`, `DeviceConfig` dataclasses |

## Hardware context

- Target device: ZMK split keyboard (tested on Corne)
- Connection: BLE, central-peripheral (left=central connects to PC, right=peripheral connects to left)
- Peripheral battery is proxied through the central half
- Required ZMK firmware config:
  ```
  CONFIG_ZMK_BATTERY_REPORTING=y
  CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING=y
  CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY=y
  ```
- `CONFIG_BT_BAS` is NOT required

## Development rules

- After any code change, update all affected files (README.md, CLAUDE.md, CHANGELOG.md, configs, comments) in the same commit
- Always push to GitHub after committing unless told otherwise
- Config follows XDG: `~/.config/keebat/keebat.toml`
- Device name in config supports glob patterns (e.g. `Corne*`)
- Log level is configurable via `[logging] level` in config (default: `WARNING`)

## Useful commands

```bash
# Install in dev mode
pip install -e .

# Run
keebat

# Inspect BLE devices via D-Bus
busctl tree org.bluez

# Read battery characteristics manually
dbus-send --system --print-reply --dest=org.bluez \
  /org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX/serviceNNNN/charNNNN \
  org.bluez.GattCharacteristic1.ReadValue dict:string:variant:
```
