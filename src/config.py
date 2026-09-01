"""Config loading, file paths, and backend-agnostic key-name validation."""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
REGISTRY_PATH = ROOT / "devices.json"
LOG_PATH = ROOT / "click_bridge.log"

# Vocabularies used to validate a mapping at load time. The actual key objects
# are built per backend (pynput Key / evdev keycode).
SPECIAL_NAMES = {
    "space", "enter", "return", "esc", "escape", "tab",
    "backspace", "delete", "del", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "plus", "minus",
} | {f"f{i}" for i in range(1, 13)}
MOD_NAMES = {"ctrl", "control", "shift", "alt", "cmd", "win", "super"}


def parse_spec(spec: str):
    """Parse "ctrl+c" -> (["ctrl"], "c", True).

    Raises KeyError for an unknown modifier and ValueError for an unknown key
    name, so load_config can reject a bad mapping regardless of backend.
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
    with open(CONFIG_PATH, "rb") as f:
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
