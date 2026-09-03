import asyncio
import sys
import tomllib
from pathlib import Path

from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError
from pynput.keyboard import Controller, Key

# --- Click service characteristics -------------------------------------------
CONTROL_POINT = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: handshake
RESPONSE      = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate: handshake reply
MEASURED      = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify: button data
HANDSHAKE = b"RideOn"
BUTTON_MSG_TYPE = 0x23

# bit index in the 32-bit active-low mask -> button name
BUTTONS = {4: "A", 5: "B", 6: "Y", 7: "Z", 12: "PLUS"}

RETRY_DELAY = 3.0   # seconds between reconnect attempts
SCAN_TIMEOUT = 20.0

# --- key name resolution -----------------------------------------------------
SPECIAL = {
    "space": Key.space, "enter": Key.enter, "return": Key.enter,
    "esc": Key.esc, "escape": Key.esc, "tab": Key.tab,
    "backspace": Key.backspace, "delete": Key.delete, "del": Key.delete,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end, "pageup": Key.page_up, "pagedown": Key.page_down,
    "plus": "+", "minus": "-",
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}
MODS = {
    "ctrl": Key.ctrl, "control": Key.ctrl, "shift": Key.shift,
    "alt": Key.alt, "cmd": Key.cmd, "win": Key.cmd, "super": Key.cmd,
}


def resolve(spec: str):
    """Parse a config value like 'up' or 'ctrl+c' into (mods, main_key, is_combo)."""
    tokens = [t.strip().lower() for t in spec.split("+") if t.strip()]
    if not tokens:            # the spec was literally "+"
        tokens = ["plus"]
    *mod_names, key_name = tokens
    mods = [MODS[m] for m in mod_names]
    main = SPECIAL.get(key_name, key_name)
    if isinstance(main, str) and len(main) != 1:
        raise ValueError(f"Unknown key name: {key_name!r}")
    return mods, main, bool(mods)


def load_config():
    path = Path(__file__).parent / "config.toml"
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    address = cfg["device"]["address"]
    keymap = {}
    for button, spec in cfg["buttons"].items():
        try:
            keymap[button] = resolve(spec)
        except (KeyError, ValueError) as e:
            sys.exit(f"config.toml: bad mapping for {button} = {spec!r}: {e}")
    return address, keymap


# --- protobuf button-mask parsing --------------------------------------------
def read_varint(data, offset):
    result = shift = 0
    while True:
        b = data[offset]; offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, offset
        shift += 7


def parse_button_mask(data: bytearray):
    if not data or data[0] != BUTTON_MSG_TYPE:
        return None
    offset, mask = 1, None
    while offset < len(data):
        tag = data[offset]; offset += 1
        if (tag & 0x07) != 0:
            break
        value, offset = read_varint(data, offset)
        if (tag >> 3) == 1:
            mask = value & 0xFFFFFFFF
    return mask


# --- turn presses into keystrokes --------------------------------------------
class Keyboard:
    def __init__(self, keymap):
        self.keymap = keymap
        self.kb = Controller()
        self.held = {}

    def press(self, button):
        entry = self.keymap.get(button)
        if not entry:
            return
        mods, main, is_combo = entry
        if is_combo:
            for m in mods:
                self.kb.press(m)
            self.kb.press(main); self.kb.release(main)
            for m in reversed(mods):
                self.kb.release(m)
        else:
            self.kb.press(main)
            self.held[button] = main

    def release(self, button):
        main = self.held.pop(button, None)
        if main is not None:
            self.kb.release(main)

    def release_all(self):
        for main in self.held.values():
            self.kb.release(main)
        self.held.clear()


class Tracker:
    def __init__(self, keyboard, label=""):
        self.kb = keyboard
        self.label = label
        self.pressed = 0

    def reset(self):
        self.pressed = 0

    def update(self, mask):
        now = (~mask) & 0xFFFFFFFF
        newly_pressed = now & ~self.pressed
        newly_released = ~now & self.pressed & 0xFFFFFFFF
        self.pressed = now
        for bit in range(32):
            name = BUTTONS.get(bit)
            if not name:
                continue
            if newly_pressed & (1 << bit):
                print(f"{self.label}PRESS   {name}")
                self.kb.press(name)
            if newly_released & (1 << bit):
                print(f"{self.label}RELEASE {name}")
                self.kb.release(name)


# --- one device, with reconnect ----------------------------------------------
async def run_device(address, keymap, label=""):
    keyboard = Keyboard(keymap)
    tracker = Tracker(keyboard, label=label)

    def on_measured(sender, data):
        mask = parse_button_mask(data)
        if mask is not None:
            tracker.update(mask)

    while True:
        try:
            print(f"{label}scanning for {address} (press a button to wake it)...")
            device = await BleakScanner.find_device_by_address(address, timeout=SCAN_TIMEOUT)
            if device is None:
                print(f"{label}not found; retrying...")
                await asyncio.sleep(RETRY_DELAY)
                continue

            loop = asyncio.get_running_loop()
            disconnected = asyncio.Event()

            def on_disconnect(_client):
                loop.call_soon_threadsafe(disconnected.set)

            print(f"{label}connecting...")
            async with BleakClient(device, disconnected_callback=on_disconnect) as client:
                tracker.reset()
                await client.start_notify(RESPONSE, lambda s, d: None)
                await client.start_notify(MEASURED, on_measured)
                await client.write_gatt_char(CONTROL_POINT, HANDSHAKE, response=False)
                print(f"{label}ready.\n")
                await disconnected.wait()
                print(f"{label}disconnected.")
        except asyncio.CancelledError:
            raise
        except (BleakError, asyncio.TimeoutError, EOFError, OSError) as e:
            print(f"{label}connection error: {e}")
        finally:
            keyboard.release_all()
        print(f"{label}reconnecting in {RETRY_DELAY:.0f}s...\n")
        await asyncio.sleep(RETRY_DELAY)


async def main():
    address, keymap = load_config()
    await run_device(address, keymap)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")