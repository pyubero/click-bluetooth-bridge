# CLAUDE.md

## Project Overview

A Bluetooth bridge that translates button presses from Click cycling controllers into keyboard inputs. Connects to one or more Click controllers (two button layouts: ABXY or d-pad), decodes their protobuf button messages, and injects the corresponding keystrokes into the system (kernel uinput on Linux/Wayland, pynput on Windows/X11).

**Key components:**
- **src/** — The bridge package, one module per concern (run `python -m src.main`):
  - **main.py** — entry point: logging setup, discovery orchestration, per-device tasks
  - **config.py** — file paths, config loading, key-name validation
  - **protocol.py** — Click/standard characteristic UUIDs, button-mask parsing
  - **discovery.py** — shared BLE scanner, auto-discovery, controller identification
  - **device.py** — per-controller `Tracker` and the reconnecting device loop
  - **keyboard.py** — `UinputKeyboard`/`PynputKeyboard` backends and `make_keyboard`
  - **registry.py** — `Registry` (persistent device sightings in devices.json)
- **helpers/** — Utility scripts for discovery, debugging, device info, and button decoding
- **config.toml** — User-facing button-to-key mapping and controller MAC addresses
- **devices.json** — Auto-populated registry of seen controllers (MAC, serial, firmware, timestamps)

## Environment Setup

The project uses Conda with Python 3.11, pinning key dependencies for cross-platform compatibility (Linux BlueZ, Windows WinRT):

```bash
# Create and activate environment
conda env create -f environment.yml
conda activate click-bridge

# Or update if environment exists
conda env update -f environment.yml --prune
```

Key dependencies:
- **bleak** ≥0.22 — BLE client for Linux (BlueZ) and Windows (WinRT)
- **pynput** ≥1.7 — Keystroke injection on Windows and Linux/X11
- **evdev** ≥1.6 (Linux only, pip) — kernel-level `/dev/uinput` virtual keyboard; used automatically on Wayland so the compositor never prompts for input permission
- **protobuf** ≥4.25 — Decode varint-encoded button masks in button messages

### Keystroke injection backends

`make_keyboard()` auto-selects the injector; no `config.toml` change is needed:
- **Linux/Wayland (and X11):** `UinputKeyboard` — a kernel `/dev/uinput` virtual keyboard via evdev. Injecting below the display server means Wayland treats it as ordinary hardware and never prompts.
- **Windows, or Linux when uinput is unavailable:** `PynputKeyboard` (the pynput backend).

**One-time uinput access** (`/dev/uinput` is root-only by default). Install the shipped udev rule and join the `input` group; without this the bridge falls back to pynput (Wayland may keep prompting):

```bash
sudo cp helpers/99-uinput.rules /etc/udev/rules.d/99-uinput.rules
sudo modprobe uinput
sudo usermod -aG input "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger
# then log out/in (or reboot) for the input-group membership to apply
```

## Running the Application

```bash
# Run the main bridge
python -m src.main

# Expected output during startup:
#   "Loaded 2 controller(s): abxy, dpad"
#   "[abxy] discovering a controller..."
#   "[dpad] discovering a controller..."
#   "[abxy] assigned -> F4:C4:59:03:BC:6F"
#   "[dpad] assigned -> F4:C4:59:03:A0:F3"
#   "[abxy] ready."
#   "[dpad] ready."
```

The process auto-discovers controllers if no fixed MAC address is configured, or connects to known addresses. Each controller runs in its own async task with automatic reconnection on disconnect.

## Configuration

**config.toml** defines controller blocks (name, optional fixed MAC address, button-to-key mapping):
- Buttons: A, B, Y, Z, PLUS (ABXY layout) or UP, DOWN, LEFT, RIGHT, MINUS (d-pad layout)
- Keys: single characters ("a", "5"), special names (space, enter, up, down, etc.), F keys (f1–f12), or combos with "+" (ctrl+c, shift+a)
- Auto-discovery: omit the `address` line to let the tool assign the next discovered controller

## Tests

The only good high level test is a real world test button by button. If necessary ask me to do a full test.

## Architecture & Code Patterns

**Discovery & Connection Flow:**
1. `main()` loads config and creates a shared `Discovery` scanner (listens for all Click devices in range)
2. Fixed-address controllers connect immediately; auto-assigned slots wait for `claim_next()` to find a free controller
3. Per-device loop (`run_device`) connects, sends handshake, spawns notification listeners, and handles reconnection

**Button Message Decoding:**
- Messages are protobuf with type byte 0x23 followed by varint-encoded fields
- Field 1 (tag >> 3 == 1) is the 32-bit button mask (active-low, bits 0–7 for d-pad or ABXY, bits 8/12 for MINUS/PLUS)
- `parse_button_mask()` extracts the mask; `Tracker.update()` compares old vs. new state to fire press/release events

**Key Concepts:**
- **Active-low mask:** bit=0 means button pressed; bit=1 means released
- **Held keys vs. combos:** single keys stay held until release; combos (with modifiers) fire and release instantly
- **Tracker:** per-controller state machine that monitors bit changes and calls `Keyboard.press/release`
- **Registry:** thread-safe device sighting recorder (first/last seen, serial, firmware); throttles writes to 30s intervals

**Characteristic UUIDs** (Click service 19ca-4651-86e5-fa29dcdd09d1):
- 00000003: CONTROL_POINT (write handshake)
- 00000004: RESPONSE (indicate handshake reply)
- 00000002: MEASURED (notify button data)

## Known Issues & TODOs

See **ISSUES.md** for backlog.
Whenever an issue is fixed, briefly explain the modifications in /issues/{issue_slug}.md

## Development Notes

- **Thread safety:** discovery callbacks run in the scanner's thread; use `loop.call_soon_threadsafe()` for async signaling
- **Resource cleanup:** always use `async with BleakClient` and await `BleakScanner.stop()` to prevent hanging
- **Error resilience:** connection errors trigger reconnect with 3-second backoff; battery reads are logged only on change
- **Config validation:** `load_config()` exits early on bad keymaps (unknown key names, invalid modifiers)

## Development Rules

1. Think Before Coding: **Don't assume. Don't hide confusion. Surface tradeoffs.**
Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

2. Simplicity First: **Minimum code that solves the problem. Nothing speculative.**
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

3. Surgical Changes: **Touch only what you must. Clean up only your own mess.**
When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

4. Goal-Driven Execution: **Define success criteria. Loop until verified.**
Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"