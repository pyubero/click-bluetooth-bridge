"""Show how the uinput backend resolves config keys for the active layout.

Prints the raw layout-detection sources, the chosen layout, and for every button
in config.toml the evdev keycode + modifiers it will inject. Run it in the SAME
terminal/session you launch the bridge from, so it sees the same environment.

    python -m helpers.show_layout
"""

import os
import subprocess
import sys
from pathlib import Path

# Allow running as a plain script (python helpers/show_layout.py) too, not just
# as a module (python -m helpers.show_layout): put the repo root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evdev import ecodes as e

from src.config import load_config
from src.keyboard import _build_char_map, _detect_layout


def keyname(code):
    for n in dir(e):
        if n.startswith("KEY_") and getattr(e, n) == code:
            return n
    return f"code {code}"


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        return out.stdout.strip() or f"(rc={out.returncode}, no output)"
    except (OSError, subprocess.SubprocessError) as ex:
        return f"(unavailable: {ex})"


def main():
    print("=== layout detection sources ===")
    print("setxkbmap -query:\n  " + _run(["setxkbmap", "-query"]).replace("\n", "\n  "))
    print("localectl status:\n  " + _run(["localectl", "status"]).replace("\n", "\n  "))
    print("XKB_DEFAULT_LAYOUT =", os.environ.get("XKB_DEFAULT_LAYOUT", "(unset)"))
    print("XKB_DEFAULT_VARIANT =", os.environ.get("XKB_DEFAULT_VARIANT", "(unset)"))
    print("WAYLAND_DISPLAY =", os.environ.get("WAYLAND_DISPLAY", "(unset)"))
    print("XDG_SESSION_TYPE =", os.environ.get("XDG_SESSION_TYPE", "(unset)"))
    print("================================\n")

    layout, variant = _detect_layout()
    print(f"detected layout: {layout}" + (f"-{variant}" if variant else ""))

    charmap = _build_char_map(e)
    if charmap is None:
        print("xkbcommon unavailable -> the backend uses the US fallback tables.")
        return

    named = {"space", "enter", "return", "esc", "escape", "tab", "backspace",
             "delete", "del", "up", "down", "left", "right", "home", "end",
             "pageup", "pagedown", *(f"f{i}" for i in range(1, 13))}
    aliases = {"plus": "+", "minus": "-"}

    for ctrl in load_config():
        print(f"\n[{ctrl['name']}]")
        for button, (mods, key_name, _combo) in ctrl["keymap"].items():
            name = aliases.get(key_name, key_name)
            prefix = "+".join(mods) + "+" if mods else ""
            if name in named:
                print(f"  {button:6} {key_name!r:8} -> (named key)")
            elif name in charmap:
                kc, kmods = charmap[name]
                extra = " ".join(keyname(m) for m in kmods)
                print(f"  {button:6} {prefix + key_name!r:10} -> {keyname(kc)}"
                      + (f" + {extra}" if extra else ""))
            else:
                print(f"  {button:6} {key_name!r:8} -> NOT PRODUCIBLE on this layout")


if __name__ == "__main__":
    main()
