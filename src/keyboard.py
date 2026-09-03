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
import subprocess
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


def _layout_from_env():
    layout = os.environ.get("XKB_DEFAULT_LAYOUT", "").split(",")[0].strip()
    variant = os.environ.get("XKB_DEFAULT_VARIANT", "").split(",")[0].strip()
    return (layout, variant) if layout else None


def _layout_from_localectl():
    try:
        out = subprocess.run(["localectl", "status"],
                             capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    layout = variant = ""
    for line in out.stdout.splitlines():
        s = line.strip()
        if s.startswith("X11 Layout:"):
            layout = s.split(":", 1)[1].strip().split(",")[0]
        elif s.startswith("X11 Variant:"):
            variant = s.split(":", 1)[1].strip().split(",")[0]
    return (layout, variant) if layout else None


def _layout_from_setxkbmap():
    try:
        out = subprocess.run(["setxkbmap", "-query"],
                             capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    layout = variant = ""
    for line in out.stdout.splitlines():
        if line.startswith("layout:"):
            layout = line.split(":", 1)[1].strip().split(",")[0]
        elif line.startswith("variant:"):
            variant = line.split(":", 1)[1].strip().split(",")[0]
    return (layout, variant) if layout else None


def _detect_layout():
    """Best-effort active XKB layout as (layout, variant).

    uinput injects physical keycodes, so the character a key produces depends on
    the user's layout. Source priority differs by session type: under Wayland,
    `setxkbmap` queries XWayland, which usually reports its own US default rather
    than the real layout, so trust the session env (XKB_DEFAULT_LAYOUT, which is
    what libxkbcommon itself uses) and `localectl` ahead of it. On X11, setxkbmap
    queries the real server and is authoritative. First hit wins; default to US.
    """
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    if wayland:
        sources = [_layout_from_env, _layout_from_localectl, _layout_from_setxkbmap]
    else:
        sources = [_layout_from_setxkbmap, _layout_from_localectl, _layout_from_env]
    for source in sources:
        got = source()
        if got:
            return got
    return "us", ""


_CHAR_MAP_UNBUILT = object()  # sentinel: charmap not built yet
_char_map = _CHAR_MAP_UNBUILT


def _build_char_map(e):
    """{char: (evdev_keycode, [modifier_keycodes])} for the active layout, using
    libxkbcommon (the same library the compositor uses). Returns None if xkbcommon
    is unavailable or the layout can't be loaded, so the caller falls back to the
    hardcoded US tables.

    Built once and cached so every controller resolves keys identically (detecting
    per-controller could otherwise diverge, e.g. one gets the real layout and
    another the US default if a detection subprocess momentarily fails).
    """
    global _char_map
    if _char_map is not _CHAR_MAP_UNBUILT:
        return _char_map
    _char_map = _compute_char_map(e)
    return _char_map


def _compute_char_map(e):
    try:
        from xkbcommon import xkb
    except ImportError:
        return None

    layout, variant = _detect_layout()
    try:
        km = xkb.Context().keymap_new_from_names(layout=layout,
                                                 variant=variant or None)
    except Exception as ex:  # bad layout name, missing xkb data, etc.
        log.warning("[uinput] could not load layout %r (%s); using US fallback.",
                    layout, ex)
        return None

    mod_names = [km.mod_get_name(i) for i in range(km.num_mods())]
    # XKB modifier name -> the evdev modifier key we can actually emit.
    mod_to_evdev = {
        "Shift": e.KEY_LEFTSHIFT,
        "Mod5": e.KEY_RIGHTALT, "LevelThree": e.KEY_RIGHTALT,  # AltGr
        "Control": e.KEY_LEFTCTRL,
        "Mod1": e.KEY_LEFTALT, "Alt": e.KEY_LEFTALT,
        "Mod4": e.KEY_LEFTMETA, "Super": e.KEY_LEFTMETA,
    }

    def mods_for_level(kc, lvl):
        """Simplest emittable modifier-keycode list for a (key, level), or None
        if every option needs a modifier we can't emit (or caps lock)."""
        best = None
        for mask in km.key_get_mods_for_level(kc, 0, lvl):
            names = [mod_names[i] for i in range(len(mod_names)) if mask & (1 << i)]
            if "Lock" in names:  # don't depend on caps-lock state
                continue
            codes, ok = [], True
            for n in names:
                code = mod_to_evdev.get(n)
                if code is None:
                    ok = False
                    break
                if code not in codes:
                    codes.append(code)
            if ok and (best is None or len(codes) < len(best)):
                best = codes
        return best

    def sym_char(sym):
        try:
            s = xkb.keysym_to_string(sym)
        except Exception:
            return None
        return s if (s and len(s) == 1 and s.isprintable()) else None

    best = {}  # char -> (level, evdev_keycode, [modifier_keycodes])
    for kc in range(km.min_keycode(), km.max_keycode() + 1):
        evdev_code = kc - 8  # XKB keycodes are offset by 8 from evdev
        if evdev_code < 0:
            continue
        for lvl in range(km.num_levels_for_key(kc, 0)):
            mods = mods_for_level(kc, lvl)
            if mods is None:
                continue
            for sym in km.key_get_syms_by_level(kc, 0, lvl):
                ch = sym_char(sym)
                if not ch:
                    continue
                prev = best.get(ch)
                if prev is None or (lvl, evdev_code) < (prev[0], prev[1]):
                    best[ch] = (lvl, evdev_code, mods)

    charmap = {ch: (kc, mods) for ch, (_lvl, kc, mods) in best.items()}
    log.info("[uinput] keyboard layout: %s%s (%d characters mapped).",
             layout, f"-{variant}" if variant else "", len(charmap))
    return charmap


class UinputKeyboard:
    """Kernel-level virtual keyboard. Injects below the display server, so a
    Wayland compositor treats it as ordinary hardware and never prompts."""

    def __init__(self, keymap):
        from evdev import UInput, ecodes as e

        self.keymap = keymap
        self.e = e
        self.held = {}          # button -> list of keycodes to release

        named = self._named_keys(e)          # layout-independent function keys
        charmap = _build_char_map(e)         # layout-aware char -> keycode+mods
        us_keytab, us_shifted = self._tables(e)  # US fallback if charmap is None
        mod_codes = {
            "ctrl": e.KEY_LEFTCTRL, "control": e.KEY_LEFTCTRL,
            "shift": e.KEY_LEFTSHIFT, "alt": e.KEY_LEFTALT,
            "cmd": e.KEY_LEFTMETA, "win": e.KEY_LEFTMETA, "super": e.KEY_LEFTMETA,
        }
        aliases = {"plus": "+", "minus": "-"}  # word-names -> their character

        # resolve tokens -> (all_mod_keycodes, keycode, is_combo)
        self.resolved = {}
        used = {e.KEY_LEFTSHIFT}
        for button, (mod_names, key_name, is_combo) in keymap.items():
            combo_mods = [mod_codes[m] for m in mod_names]
            name = aliases.get(key_name, key_name)
            if name in named:                # space, enter, arrows, f-keys, ...
                keycode, layout_mods = named[name], []
            elif charmap is not None:        # single character, active layout
                hit = charmap.get(name)
                if hit is None:
                    log.warning("[uinput] %s = %r not producible on this layout; "
                                "skipping.", button, key_name)
                    continue
                keycode, layout_mods = hit
            elif name in us_keytab:          # xkbcommon unavailable: US fallback
                keycode, layout_mods = us_keytab[name], []
            elif name in us_shifted:
                keycode, layout_mods = us_shifted[name], [e.KEY_LEFTSHIFT]
            else:
                log.warning("[uinput] %s = %r unsupported; skipping.",
                            button, key_name)
                continue
            all_mods = combo_mods + list(layout_mods)
            self.resolved[button] = (all_mods, keycode, is_combo)
            used.update(all_mods)
            used.add(keycode)

        self.ui = UInput({e.EV_KEY: sorted(used)}, name="click-bridge")

    @staticmethod
    def _named_keys(e):
        """Layout-independent function/navigation keys, by name -> evdev keycode.
        Printable characters are resolved per-layout via _build_char_map instead."""
        kt = {
            "space": e.KEY_SPACE, "enter": e.KEY_ENTER, "return": e.KEY_ENTER,
            "esc": e.KEY_ESC, "escape": e.KEY_ESC, "tab": e.KEY_TAB,
            "backspace": e.KEY_BACKSPACE, "delete": e.KEY_DELETE, "del": e.KEY_DELETE,
            "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
            "home": e.KEY_HOME, "end": e.KEY_END,
            "pageup": e.KEY_PAGEUP, "pagedown": e.KEY_PAGEDOWN,
        }
        for i in range(1, 13):
            kt[f"f{i}"] = getattr(e, f"KEY_F{i}")
        return kt

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
        mods, keycode, is_combo = entry
        if is_combo:
            self._emit(mods, 1)
            self._emit([keycode], 1)
            self._emit([keycode], 0)
            self._emit(list(reversed(mods)), 0)
        else:
            down = list(mods) + [keycode]
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
