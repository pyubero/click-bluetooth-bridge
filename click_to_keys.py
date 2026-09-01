import asyncio
import json
import os
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError
# NOTE: pynput is imported lazily inside PynputKeyboard. Importing it at module
# load fails on a pure-Wayland/headless box (no X connection), which would stop
# the uinput backend from ever running. See make_keyboard().

# --- Zwift service characteristics -------------------------------------------
CONTROL_POINT = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: handshake
RESPONSE      = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate: handshake reply
MEASURED      = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify: button data
HANDSHAKE = b"RideOn"
BUTTON_MSG_TYPE = 0x23

# --- standard characteristics ------------------------------------------------
BATTERY     = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
DIS = {  # human label -> Device Information Service characteristic
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "serial":       "00002a25-0000-1000-8000-00805f9b34fb",
    "firmware":     "00002a26-0000-1000-8000-00805f9b34fb",
    "hardware":     "00002a27-0000-1000-8000-00805f9b34fb",
}

# How we recognise a Zwift controller during auto-discovery.
ZWIFT_NAME_HINT = "zwift"
ZWIFT_SERVICE_UUIDS = {
    "0000fc82-0000-1000-8000-00805f9b34fb",   # newer firmware
    "00000001-19ca-4651-86e5-fa29dcdd09d1",   # older firmware
}

REGISTRY_PATH = Path(__file__).parent / "devices.json"
BATTERY_POLL_INTERVAL = 120.0   # seconds between battery reads
RETRY_DELAY = 3.0

# bit index in the 32-bit active-low mask -> button name.
BUTTONS = {
    # directional variant (d-pad + minus)
    0: "LEFT", 1: "UP", 2: "RIGHT", 3: "DOWN", 8: "MINUS",
    # ABXY variant (A/B/Y/Z + plus)
    4: "A", 5: "B", 6: "Y", 7: "Z", 12: "PLUS",
}

# --- key name resolution -----------------------------------------------------
# Backend-agnostic vocabularies used to validate a mapping at config load. The
# actual key objects are built per backend (pynput Key / evdev keycode).
SPECIAL_NAMES = {
    "space", "enter", "return", "esc", "escape", "tab",
    "backspace", "delete", "del", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "plus", "minus",
} | {f"f{i}" for i in range(1, 13)}
MOD_NAMES = {"ctrl", "control", "shift", "alt", "cmd", "win", "super"}


def parse_spec(spec: str):
    """Backend-agnostic parse: "ctrl+c" -> (["ctrl"], "c", True).

    Returns (mod_names, key_name, is_combo). Raises KeyError for an unknown
    modifier and ValueError for an unknown key name, so load_config() can
    reject a bad mapping at startup regardless of the injection backend.
    """
    tokens = [t.strip().lower() for t in spec.split("+") if t.strip()]
    if not tokens:
        tokens = ["plus"]
    *mod_names, key_name = tokens
    for m in mod_names:
        if m not in MOD_NAMES:
            raise KeyError(m)
    if key_name not in SPECIAL_NAMES and len(key_name) != 1:
        raise ValueError(f"Unknown key name: {key_name!r}")
    return mod_names, key_name, bool(mod_names)


def load_config():
    """Return a list of dicts: {name, address (or None), keymap}."""
    path = Path(__file__).parent / "config.toml"
    with open(path, "rb") as f:
        cfg = tomllib.load(f)

    blocks = cfg.get("controller")
    if not blocks:
        sys.exit("config.toml: no [[controller]] blocks found.")

    controllers = []
    for i, block in enumerate(blocks):
        name = block.get("name", f"controller{i + 1}")
        address = block.get("address")  # optional -> auto-discover
        keymap = {}
        for button, spec in block.get("buttons", {}).items():
            try:
                keymap[button.upper()] = parse_spec(spec)
            except (KeyError, ValueError) as e:
                sys.exit(f"config.toml [{name}]: bad mapping for {button} = {spec!r}: {e}")
        controllers.append({"name": name, "address": address, "keymap": keymap})
    return controllers


# --- persistent device registry ----------------------------------------------
class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        self._last_save = 0.0
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))
            self._last_save = time.monotonic()
        except Exception as e:
            print(f"(could not write {self.path.name}: {e})")

    def record_sighting(self, mac, name):
        now = datetime.now().isoformat(timespec="seconds")
        entry = self.data.setdefault(mac, {})
        is_new = "first_seen" not in entry
        if is_new:
            entry["first_seen"] = now
        entry["last_seen"] = now
        if name and not entry.get("name"):
            entry["name"] = name
        # throttle disk writes: always on a brand-new device, else every 30 s
        if is_new or (time.monotonic() - self._last_save) > 30:
            self._save()

    def record_details(self, mac, details):
        entry = self.data.setdefault(mac, {})
        for k, v in details.items():
            if v:
                entry[k] = v
        self._save()

    def flush(self):
        self._save()


# --- shared scanner + auto-discovery -----------------------------------------
class Discovery:
    def __init__(self, registry):
        self.registry = registry
        self.devices = {}                    # MAC -> BLEDevice (Zwift only)
        self._events = {}                    # MAC -> asyncio.Event
        self._new = asyncio.Event()          # fires when a new Zwift MAC appears
        self._scanner = BleakScanner(detection_callback=self._detected)

    @staticmethod
    def _is_zwift(device, adv):
        name = (getattr(device, "name", None) or getattr(adv, "local_name", None) or "")
        if ZWIFT_NAME_HINT in name.lower():
            return True
        uuids = {u.lower() for u in (adv.service_uuids or [])}
        return bool(uuids & ZWIFT_SERVICE_UUIDS)

    def _detected(self, device, adv):
        if not self._is_zwift(device, adv):
            return
        mac = device.address.upper()
        is_new = mac not in self.devices
        self.devices[mac] = device
        self.registry.record_sighting(mac, getattr(device, "name", None) or "Zwift Click")
        self._events.setdefault(mac, asyncio.Event()).set()
        if is_new:
            self._new.set()

    async def __aenter__(self):
        await self._scanner.start()
        return self

    async def __aexit__(self, *exc):
        await self._scanner.stop()

    async def wait_for(self, address):
        mac = address.upper()
        ev = self._events.setdefault(mac, asyncio.Event())
        await ev.wait()
        ev.clear()
        return self.devices[mac]

    async def claim_next(self, exclude):
        """Return a Zwift MAC not in `exclude` (waits until one appears)."""
        while True:
            for mac in self.devices:
                if mac not in exclude:
                    return mac
            self._new.clear()
            await self._new.wait()


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


# --- keystrokes ---------------------------------------------------------------
# Two backends share the interface Tracker uses: press(button), release(button),
# release_all(). Each takes a keymap of {BUTTON: (mod_names, key_name, is_combo)}
# (parsed by parse_spec) and resolves it to its own key representation.
#
#   PynputKeyboard  - pynput injection (Windows, X11). Blocked/prompted on Wayland.
#   UinputKeyboard  - kernel /dev/uinput virtual keyboard via evdev; works on
#                     Wayland with no permission prompt (see make_keyboard).

class PynputKeyboard:
    def __init__(self, keymap):
        from pynput.keyboard import Controller, Key  # lazy: needs X on Linux

        special = {
            "space": Key.space, "enter": Key.enter, "return": Key.enter,
            "esc": Key.esc, "escape": Key.esc, "tab": Key.tab,
            "backspace": Key.backspace, "delete": Key.delete, "del": Key.delete,
            "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
            "home": Key.home, "end": Key.end,
            "pageup": Key.page_up, "pagedown": Key.page_down,
            "plus": "+", "minus": "-",
            **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
        }
        mods_map = {
            "ctrl": Key.ctrl, "control": Key.ctrl, "shift": Key.shift,
            "alt": Key.alt, "cmd": Key.cmd, "win": Key.cmd, "super": Key.cmd,
        }

        self.keymap = keymap
        self.kb = Controller()
        self.held = {}
        # resolve parsed tokens -> pynput objects
        self.resolved = {}
        for button, (mod_names, key_name, is_combo) in keymap.items():
            mods = [mods_map[m] for m in mod_names]
            main = special.get(key_name, key_name)
            self.resolved[button] = (mods, main, is_combo)

    def press(self, button):
        entry = self.resolved.get(button)
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


class UinputKeyboard:
    """Kernel-level virtual keyboard. Injects below the display server, so a
    Wayland compositor treats it as ordinary hardware and never prompts."""

    def __init__(self, keymap):
        from evdev import UInput, ecodes as e

        self.keymap = keymap
        self.e = e
        self.held = {}          # button -> list of keycodes to release

        keytab, shifted = self._tables(e)
        mod_codes = {
            "ctrl": e.KEY_LEFTCTRL, "control": e.KEY_LEFTCTRL,
            "shift": e.KEY_LEFTSHIFT, "alt": e.KEY_LEFTALT,
            "cmd": e.KEY_LEFTMETA, "win": e.KEY_LEFTMETA, "super": e.KEY_LEFTMETA,
        }

        # resolve tokens -> (mod_keycodes, (keycode, needs_shift), is_combo)
        self.resolved = {}
        used = {e.KEY_LEFTSHIFT}
        for button, (mod_names, key_name, is_combo) in keymap.items():
            mods = [mod_codes[m] for m in mod_names]
            if key_name in keytab:
                keycode, needs_shift = keytab[key_name], False
            elif key_name in shifted:
                keycode, needs_shift = shifted[key_name], True
            else:
                raise ValueError(f"uinput: unsupported key {key_name!r}")
            self.resolved[button] = (mods, (keycode, needs_shift), is_combo)
            used.update(mods)
            used.add(keycode)

        self.ui = UInput({e.EV_KEY: sorted(used)}, name="zwift-click")

    @staticmethod
    def _tables(e):
        """(unshifted, shifted) maps from parse_spec key names to evdev keycodes."""
        keytab = {}
        for ch in "abcdefghijklmnopqrstuvwxyz":
            keytab[ch] = getattr(e, f"KEY_{ch.upper()}")
        for d in "0123456789":
            keytab[d] = getattr(e, f"KEY_{d}")
        keytab.update({
            "space": e.KEY_SPACE, "enter": e.KEY_ENTER, "return": e.KEY_ENTER,
            "esc": e.KEY_ESC, "escape": e.KEY_ESC, "tab": e.KEY_TAB,
            "backspace": e.KEY_BACKSPACE, "delete": e.KEY_DELETE, "del": e.KEY_DELETE,
            "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
            "home": e.KEY_HOME, "end": e.KEY_END,
            "pageup": e.KEY_PAGEUP, "pagedown": e.KEY_PAGEDOWN,
            "minus": e.KEY_MINUS, "-": e.KEY_MINUS, "=": e.KEY_EQUAL,
            "[": e.KEY_LEFTBRACE, "]": e.KEY_RIGHTBRACE, ";": e.KEY_SEMICOLON,
            "'": e.KEY_APOSTROPHE, "`": e.KEY_GRAVE, "\\": e.KEY_BACKSLASH,
            ",": e.KEY_COMMA, ".": e.KEY_DOT, "/": e.KEY_SLASH,
        })
        for i in range(1, 13):
            keytab[f"f{i}"] = getattr(e, f"KEY_F{i}")
        # characters that are shift + another key
        shifted = {
            "plus": e.KEY_EQUAL, "+": e.KEY_EQUAL, "_": e.KEY_MINUS,
            "?": e.KEY_SLASH, ":": e.KEY_SEMICOLON, "\"": e.KEY_APOSTROPHE,
            "<": e.KEY_COMMA, ">": e.KEY_DOT, "~": e.KEY_GRAVE, "|": e.KEY_BACKSLASH,
            "!": e.KEY_1, "@": e.KEY_2, "#": e.KEY_3, "$": e.KEY_4, "%": e.KEY_5,
            "^": e.KEY_6, "&": e.KEY_7, "*": e.KEY_8, "(": e.KEY_9, ")": e.KEY_0,
        }
        return keytab, shifted

    def _emit(self, codes, value):
        for c in codes:
            self.ui.write(self.e.EV_KEY, c, value)
        self.ui.syn()

    def press(self, button):
        entry = self.resolved.get(button)
        if not entry:
            return
        mods, (keycode, needs_shift), is_combo = entry
        if is_combo:
            down = list(mods) + ([self.e.KEY_LEFTSHIFT] if needs_shift else [])
            self._emit(down, 1)
            self._emit([keycode], 1)
            self._emit([keycode], 0)
            self._emit(list(reversed(down)), 0)
        else:
            down = ([self.e.KEY_LEFTSHIFT] if needs_shift else []) + [keycode]
            self._emit(down, 1)
            self.held[button] = down

    def release(self, button):
        down = self.held.pop(button, None)
        if down is not None:
            self._emit(list(reversed(down)), 0)

    def release_all(self):
        for down in self.held.values():
            self._emit(list(reversed(down)), 0)
        self.held.clear()

    def close(self):
        try:
            self.ui.close()
        except Exception:
            pass


_UINPUT_SETUP = (
    "  echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' "
    "| sudo tee /etc/udev/rules.d/99-uinput.rules\n"
    "  sudo modprobe uinput\n"
    "  sudo usermod -aG input \"$USER\"\n"
    "  sudo udevadm control --reload-rules && sudo udevadm trigger\n"
    "  # then log out/in (or reboot) for the input-group membership to apply"
)
_warned_uinput = False
_announced_uinput = False


def make_keyboard(keymap):
    """Pick the injection backend. On Linux prefer the Wayland-safe uinput
    virtual keyboard; fall back to pynput (Windows, X11, or uinput unavailable)."""
    global _warned_uinput, _announced_uinput
    if sys.platform.startswith("linux"):
        try:
            import evdev  # noqa: F401
        except ImportError:
            evdev = None
        if evdev is not None and os.access("/dev/uinput", os.W_OK):
            try:
                kb = UinputKeyboard(keymap)
                if not _announced_uinput:
                    print("Injecting via kernel uinput virtual keyboard (Wayland-safe).")
                    _announced_uinput = True
                return kb
            except (PermissionError, OSError, evdev.UInputError) as ex:
                if not _warned_uinput:
                    print(f"uinput unavailable ({ex}); falling back to pynput.\n"
                          f"For prompt-free injection on Wayland, grant access once:\n"
                          f"{_UINPUT_SETUP}")
                    _warned_uinput = True
        elif evdev is not None and not _warned_uinput:
            print("/dev/uinput not writable; using pynput (Wayland may prompt).\n"
                  "For prompt-free injection on Wayland, grant access once:\n"
                  f"{_UINPUT_SETUP}")
            _warned_uinput = True
    try:
        return PynputKeyboard(keymap)
    except Exception as ex:  # pynput can't init (e.g. pure Wayland, no X)
        sys.exit(
            f"No usable keystroke backend: pynput failed to start ({ex}).\n"
            "On Wayland, enable the kernel uinput backend (one-time setup):\n"
            f"{_UINPUT_SETUP}"
        )


class Tracker:
    NAME_TO_BIT = {name: bit for bit, name in BUTTONS.items()}

    def __init__(self, keyboard, label=""):
        self.kb = keyboard
        self.label = label
        self.pressed = 0
        self.owned_bits = 0
        self.bit_names = {}
        for name in keyboard.keymap:
            bit = self.NAME_TO_BIT.get(name)
            if bit is not None:
                self.owned_bits |= (1 << bit)
                self.bit_names[bit] = name

    def reset(self):
        self.pressed = 0

    def update(self, mask):
        now = (~mask) & self.owned_bits
        newly_pressed = now & ~self.pressed
        newly_released = ~now & self.pressed & self.owned_bits
        self.pressed = now
        for bit, name in self.bit_names.items():
            if newly_pressed & (1 << bit):
                print(f"{self.label}PRESS   {name}")
                self.kb.press(name)
            if newly_released & (1 << bit):
                print(f"{self.label}RELEASE {name}")
                self.kb.release(name)


async def _read_text(client, uuid):
    try:
        return bytes(await client.read_gatt_char(uuid)).decode("utf-8", "replace").strip("\x00").strip()
    except Exception:
        return None


async def record_details(client, registry, address):
    details = {"name": await _read_text(client, DEVICE_NAME)}
    for label, uuid in DIS.items():
        details[label] = await _read_text(client, uuid)
    registry.record_details(address.upper(), details)


# --- one device, with reconnect + battery ------------------------------------
async def run_device(discovery, registry, address, keymap, label=""):
    keyboard = make_keyboard(keymap)
    tracker = Tracker(keyboard, label=label)

    def on_measured(sender, data):
        mask = parse_button_mask(data)
        if mask is not None:
            tracker.update(mask)

    while True:
        try:
            print(f"{label}waiting for device (press a button to wake it)...")
            device = await discovery.wait_for(address)

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
                await record_details(client, registry, address)
                print(f"{label}ready.")

                # battery: read now, then poll until disconnect (reads avoid the
                # multi-device notification cross-talk that notify would hit)
                last_batt = None
                while not disconnected.is_set():
                    try:
                        batt = (await client.read_gatt_char(BATTERY))[0]
                        if batt != last_batt:
                            print(f"{label}battery {batt}%")
                            last_batt = batt
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(disconnected.wait(), timeout=BATTERY_POLL_INTERVAL)
                    except asyncio.TimeoutError:
                        pass
                print(f"{label}disconnected.")
        except asyncio.CancelledError:
            keyboard.release_all()
            if hasattr(keyboard, "close"):
                keyboard.close()
            raise
        except (BleakError, asyncio.TimeoutError, EOFError, OSError) as e:
            print(f"{label}connection error: {e}")
        finally:
            keyboard.release_all()
        print(f"{label}reconnecting in {RETRY_DELAY:.0f}s...")
        await asyncio.sleep(RETRY_DELAY)


async def main():
    controllers = load_config()
    registry = Registry(REGISTRY_PATH)

    fixed = [c for c in controllers if c["address"]]
    auto = [c for c in controllers if not c["address"]]
    print(f"Loaded {len(controllers)} controller(s): "
          + ", ".join(c["name"] for c in controllers))
    if auto:
        print(f"{len(auto)} will be auto-assigned to discovered Zwift controllers.")
    print()

    async with Discovery(registry) as discovery:
        # resolve auto slots to concrete MACs, in config order
        claimed = {c["address"].upper() for c in fixed}
        specs = []
        for c in controllers:
            if c["address"]:
                specs.append((c["name"], c["address"], c["keymap"]))
            else:
                print(f"[{c['name']}] discovering a controller...")
                mac = await discovery.claim_next(claimed)
                claimed.add(mac)
                print(f"[{c['name']}] assigned -> {mac}")
                specs.append((c["name"], mac, c["keymap"]))

        tasks = [
            asyncio.create_task(run_device(discovery, registry, addr, keymap, label=f"[{name}] "))
            for name, addr, keymap in specs
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            registry.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")