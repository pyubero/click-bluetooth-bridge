# Wayland asks constantly for permission for keyboard injection

## Problem

The bridge injected keystrokes with **pynput**. On a Wayland session, Wayland
deliberately blocks applications from injecting synthetic input into other
applications; pynput's Linux path ends up going through a portal / RemoteDesktop
permission flow, which pops a permission request over and over. No pynput setting
silences this — it is Wayland's security model by design.

## Fix

Inject one level lower, at the **kernel**, via `/dev/uinput` — a virtual keyboard
created with **python-evdev**. The compositor sees an ordinary hardware keyboard
and never prompts. pynput is kept for Windows and X11.

### Code (`click_to_keys.py`)

- `resolve()` → **`parse_spec()`**: backend-agnostic parse that returns
  `(mod_names, key_name, is_combo)` and still validates modifiers/key names at
  config load, so a bad `config.toml` mapping exits early as before.
- `load_config()` stores these parsed tokens as each button's keymap value.
- The old `Keyboard` class became **`PynputKeyboard`** (resolves tokens to pynput
  objects in `__init__`; behavior unchanged).
- New **`UinputKeyboard`** resolves tokens to evdev keycodes (letters, digits,
  named specials, `f1..f12`, arrows, modifiers, plus a punctuation/shifted table
  so e.g. `plus` → shift+`=`) and drives an `evdev.UInput` device with
  `write(EV_KEY, code, value)` + `syn()`. Held keys stay down; combos tap once.
- **`make_keyboard()`** auto-selects: on Linux, use `UinputKeyboard` when `evdev`
  imports and `/dev/uinput` is writable; otherwise fall back to `PynputKeyboard`
  and print the one-time setup instructions. `run_device()` calls it in place of
  `Keyboard(...)` and closes the uinput device on shutdown.

### Dependency (`environment.yml`)

Added `evdev>=1.6` as a Linux-only pip dependency (`sys_platform == 'linux'`); it
does not build on Windows.

## One-time setup (grant /dev/uinput access without root)

`/dev/uinput` is root-only by default. Install the shipped udev rule
(`helpers/99-uinput.rules`) and join the `input` group:

```bash
sudo cp helpers/99-uinput.rules /etc/udev/rules.d/99-uinput.rules
sudo modprobe uinput
sudo usermod -aG input "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger
# then log out/in (or reboot) for the input-group membership to apply
```

Until this is done the bridge still runs — it just falls back to pynput (and
Wayland may keep prompting). After it, the uinput backend is selected
automatically with no per-keystroke prompt. No `config.toml` change is required.
