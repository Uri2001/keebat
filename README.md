# keebat

System tray battery monitor for ZMK split keyboards on Linux (KDE Plasma).

Shows battery levels for **both halves** of a split keyboard connected via Bluetooth — the central (master) half and the peripheral (slave) half whose charge is proxied through the central.

## Features

- Two-bar tray icon with per-half battery level
- Color coding: green (> 40%), yellow (21–40%), red (<= 20%)
- Desktop notifications on low battery
- Auto-reconnect with exponential backoff on disconnect
- Reads battery via BlueZ D-Bus (fast path) or direct GATT (fallback)

## Requirements

- Linux with BlueZ 5.55+
- Python 3.11+
- KDE Plasma (or any DE supporting `QSystemTrayIcon`)
- ZMK keyboard with battery reporting and split battery proxy enabled

### ZMK firmware config

The following options must be enabled in your ZMK firmware build:

```ini
CONFIG_ZMK_BATTERY_REPORTING=y
CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING=y
CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY=y
```

## Installation

```bash
git clone https://github.com/Uri2001/keebat.git && cd keebat
pip install .
```

Or in editable/development mode:

```bash
pip install -e .
```

## Quick start

1. **Run keebat once** — it will create a default config file and exit with a hint:

   ```bash
   keebat
   ```

2. **Edit the config** at `~/.config/keebat/keebat.toml`:

   ```toml
   [device]
   name = "My Keyboard"        # name as it appears in Bluetooth settings
   # mac = "AA:BB:CC:DD:EE:FF" # ...or use MAC address instead
   ```

   You can find the name/address with:

   ```bash
   bluetoothctl devices Connected
   ```

3. **Run keebat again** — a tray icon will appear in the panel:

   ```bash
   keebat
   ```

   Hover over the icon to see a tooltip like:

   ```
   keebat
   Left: 85%
   Right: 72%
   ```

   Right-click the icon for **Refresh** and **Quit** options.

## Configuration

Full config reference (`~/.config/keebat/keebat.toml`):

```toml
[device]
# At least one of the two is required.
name = "My Keyboard"           # device name (supports glob patterns, e.g. "Corne*")
# mac = "AA:BB:CC:DD:EE:FF"   # Bluetooth MAC address

[battery]
poll_interval = 60             # seconds between polling reads (default: 60)
central_label = "Left"         # label for the central half in the tooltip
peripheral_label = "Right"     # label for the peripheral half

[ui]
low_battery_threshold = 20     # percent — triggers warning color and notification
notify_low_battery = true      # show desktop notification on low battery
```

## Autostart

To start keebat automatically on login, copy the desktop entry:

```bash
cp resources/keebat.desktop ~/.config/autostart/
```

## How it works

BLE and D-Bus I/O runs in a dedicated background thread (`QThread` with its own `asyncio` event loop), keeping the Qt UI responsive and avoiding thread-safety warnings.

1. **Device discovery** — finds the keyboard in BlueZ by name or MAC via D-Bus. All seen devices are logged at `DEBUG` level to help diagnose name mismatches.
2. **D-Bus GATT** — enumerates all BLE Battery Service instances (UUID `0x180F`) via BlueZ D-Bus GATT interface and reads both Battery Level characteristics (`0x2A19`) directly. The first is the central battery, the second is the peripheral battery proxied by ZMK. No explicit BLE connection needed — BlueZ already maintains it.
3. **bleak fallback** — if D-Bus GATT fails, connects via `bleak` and reads the same characteristics through the bleak GATT client.
4. **Notifications + polling** — subscribes to BLE notify on battery characteristics; polls at `poll_interval` as a safety net.
5. **Reconnection** — on disconnect, retries with exponential backoff (5 s → 120 s cap).

## License

MIT
