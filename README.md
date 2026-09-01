# Zwift Click → Keyboard Bridge

Turn one or more **Zwift Click** cycling controllers into a wireless keyboard.

This tool connects to your Click controllers over Bluetooth Low Energy, decodes
their button presses, and injects the corresponding keystrokes into your system —
so a Click button can page a music player, advance slides, trigger a shortcut, or
control any app that reads the keyboard.

Works with both button layouts:

| Layout | Buttons |
|--------|---------|
| **ABXY** | `A` `B` `Y` `Z` `PLUS` |
| **d-pad** | `UP` `DOWN` `LEFT` `RIGHT` `MINUS` |

## Features

- **Multi-controller** — run several Clicks at once, each with its own key map.
- **Auto-discovery** — leave the MAC address out and the bridge assigns the next
  controller it finds; it even tells ABXY and d-pad units apart by serial and
  binds each to its matching config block.
- **Held keys and combos** — a single key stays held while the button is held; a
  combo like `ctrl+c` fires once on press.
- **Wayland-safe injection** — on Linux it injects through a kernel `/dev/uinput`
  virtual keyboard, so Wayland treats it as ordinary hardware and never prompts.
  Falls back to [pynput](https://github.com/moses-palmer/pynput) on Windows/X11.
- **Automatic reconnection** — controllers sleep to save battery; press any button
  to wake them and the bridge reconnects on its own.
- **Battery reporting** and a rotating debug log (`click_bridge.log`).

## Requirements

- Python 3.11 (a [Conda](https://docs.conda.io/) environment is provided)
- A Bluetooth adapter
  - **Linux:** BlueZ
  - **Windows:** WinRT (built in)
- One or more Zwift Click controllers

## Install

```bash
git clone https://github.com/pyubero/bt-driver.git
cd bt-driver

conda env create -f environment.yml
conda activate zwift-click
```

To update an existing environment instead:

```bash
conda env update -f environment.yml --prune
```

### One-time uinput access (Linux / Wayland)

`/dev/uinput` is root-only by default. Grant one-time access so the bridge can use
the prompt-free kernel keyboard; without it, it falls back to pynput (and Wayland
may keep asking for input permission):

```bash
sudo cp helpers/99-uinput.rules /etc/udev/rules.d/99-uinput.rules
sudo modprobe uinput
sudo usermod -aG input "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger
# then log out/in (or reboot) for the input-group membership to apply
```

## Configure

Copy the template and edit it:

```bash
cp config.default.toml config.toml
```

Each `[[controller]]` block has a name (shown in logs), an optional `address`, and
a button-to-key map:

```toml
[[controller]]
name = "abxy"
# address = "XX:XX:XX:XX:XX:XX"   # delete/omit this line to auto-assign

[controller.buttons]
A    = "a"
B    = "b"
Y    = "y"
Z    = "z"
PLUS = "space"
```

- **With `address`** — the block always binds to that exact controller.
- **Without `address`** — it's an *auto* slot, filled from discovered controllers
  at startup; the resolved address is written back into `config.toml` for you.

**Key names:** letters, digits, and symbols (`"a"`, `"5"`, `"/"`), `plus`, `minus`,
`up` `down` `left` `right`, `space` `enter` `esc` `tab` `backspace` `delete`,
`home` `end` `pageup` `pagedown`, `f1`–`f12`, and modifiers `ctrl` `shift` `alt`
`cmd`. Combine with `+` for combos (`ctrl+c`, `shift+a`). Button names are
case-insensitive.

## Run

```bash
python click_to_keys.py          # add -v for button-by-button debug output
```

Equivalent invocations:

```bash
python -m src.main
python src/main.py
```

Typical startup:

```
Loaded 2 controller(s): abxy, dpad
discovering ...
[abxy] assigned -> F4:C4:59:03:BC:6F (serial prefix 0A)
[dpad] assigned -> F4:C4:59:03:A0:F3 (serial prefix 0B)
[abxy] ready.
[dpad] ready.
```

Press `Ctrl+C` to quit.

## Project layout

```
click_to_keys.py     Entry-point shim (runs src/main.py)
src/
  main.py            Logging, discovery orchestration, per-device tasks
  config.py          Config loading, paths, key-name validation
  protocol.py        Zwift BLE UUIDs and button-message decoding
  discovery.py       Shared scanner, auto-discovery, controller identification
  device.py          Per-controller tracker and the reconnecting device loop
  keyboard.py        uinput / pynput injection backends
  registry.py        Persistent device registry (devices.json)
helpers/             Standalone scripts for discovery, debugging, and decoding
config.toml          Your controller and key-map configuration
```

The **`helpers/`** scripts are handy when setting things up:

- `discover.py` — list nearby Zwift controllers and their addresses
- `device_info.py` — dump a controller's name, serial, firmware, battery
- `decode_buttons.py` — live-print raw button masks as you press buttons
- `handshake.py` — low-level connection/handshake experimentation

## Troubleshooting

- **Wayland keeps prompting / no keystrokes appear.** Complete the
  [uinput setup](#one-time-uinput-access-linux--wayland) and re-log in. The bridge
  logs which backend it uses at startup.
- **Controller never connects.** Clicks sleep to save power and stop advertising —
  just press a button to wake it. On Linux the bridge also clears any stale BlueZ
  bond on startup so a sleeping controller can re-advertise.
- **Auto-assign picked the wrong layout.** Set explicit `address` lines so each
  block binds to a specific controller. Use `helpers/discover.py` to find the MACs.
- **Full detail.** Everything (including every press/release) is written to
  `click_bridge.log`; run with `-v` to see debug output on the console too.

## License

Released under the [GNU General Public License v3.0](LICENSE).
