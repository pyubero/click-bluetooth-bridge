"""Keystroke injection backends.

Both share the interface Tracker uses: press(button), release(button),
release_all(). Each takes a keymap of {BUTTON: (mod_names, key_name, is_combo)}
(from config.parse_spec) and resolves it to its own key representation.

  PynputKeyboard  - pynput injection (Windows, X11). Blocked/prompted on Wayland.
  UinputKeyboard  - kernel /dev/uinput virtual keyboard via evdev; works on
                    Wayland with no permission prompt (see make_keyboard).

pynput is imported lazily: importing it at module load fails on a pure-Wayland/
headless box (no X connection), which would stop the uinput backend from running.
"""

import logging
import os
import sys

log = logging.getLogger("click_bridge")


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

        self.ui = UInput({e.EV_KEY: sorted(used)}, name="click-bridge")

    @staticmethod
    def _tables(e):
        """(unshifted, shifted) maps from key names to evdev keycodes."""
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
                    log.info("Injecting via kernel uinput virtual keyboard (Wayland-safe).")
                    _announced_uinput = True
                return kb
            except (PermissionError, OSError, evdev.UInputError) as ex:
                if not _warned_uinput:
                    log.warning("uinput unavailable (%s); falling back to pynput.\n"
                                "For prompt-free injection on Wayland, grant access once:\n%s",
                                ex, _UINPUT_SETUP)
                    _warned_uinput = True
        elif evdev is not None and not _warned_uinput:
            log.warning("/dev/uinput not writable; using pynput (Wayland may prompt).\n"
                        "For prompt-free injection on Wayland, grant access once:\n%s",
                        _UINPUT_SETUP)
            _warned_uinput = True
    try:
        return PynputKeyboard(keymap)
    except Exception as ex:  # pynput can't init (e.g. pure Wayland, no X)
        sys.exit(
            f"No usable keystroke backend: pynput failed to start ({ex}).\n"
            "On Wayland, enable the kernel uinput backend (one-time setup):\n"
            f"{_UINPUT_SETUP}"
        )
