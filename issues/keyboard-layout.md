# PLUS types "¿" and MINUS types "'" instead of "+"/"-"

## Problem

On a Wayland session the bridge injects via `UinputKeyboard`, which writes raw
kernel **keycodes** — physical key *positions*, not characters. Its `_tables()`
map was hardcoded to a **US** layout: `"+"` → `Shift+KEY_EQUAL`, `"-"` →
`KEY_MINUS`.

The user has a **Spanish QWERTY** keyboard, so the OS re-interpreted those
positions through the ES layout:

- `Shift+KEY_EQUAL` (US `=` position) is `¿` on ES → `PLUS` typed `¿`
- `KEY_MINUS` (US `-` position) is `'` on ES → `MINUS` typed `'`

Letters, digits and arrows were unaffected (same positions across QWERTY
layouts); only the symbol keys move. The `PynputKeyboard` backend was never
affected because pynput types by character.

## Fix

Make the uinput backend layout-aware: detect the active keyboard layout and
resolve each configured character to the keycode+modifiers that actually produce
it on that layout, using **libxkbcommon** (the same library the compositor uses).

### Code (`src/keyboard.py`)

- **`_detect_layout()`** → `(layout, variant)`. Source priority depends on the
  session: under **Wayland**, `setxkbmap` queries XWayland and typically reports
  its own **US** default rather than the real layout, so the env
  (`XKB_DEFAULT_LAYOUT`, what libxkbcommon itself uses) and `localectl` are tried
  first; on **X11** `setxkbmap` is authoritative and comes first. Defaults to
  `us`. (Getting this order wrong was the original miss: `setxkbmap` returned
  `us` on the user's Wayland box, so `+` still landed on `KEY_KPPLUS` — which is
  `+` on every layout, hiding the bug — while `-` landed on `KEY_MINUS` = `'` on
  Spanish.)
- **`_build_char_map(e)`** → `{char: (evdev_keycode, [modifier_keycodes])}` for
  the detected layout. Builds a keymap with xkbcommon, iterates keycodes/levels,
  reads each level's Unicode char, and records the simplest key+modifiers for it
  (XKB keycode − 8 = evdev; level modifiers mapped to `KEY_LEFTSHIFT` /
  `KEY_RIGHTALT` (AltGr) / etc.; masks needing caps-lock or an unemittable
  modifier are skipped). Returns `None` if xkbcommon is unavailable or the layout
  can't load. Built once and cached (`_build_char_map` wraps `_compute_char_map`)
  so every controller resolves keys identically.
- **`UinputKeyboard.__init__`** now resolves each button: layout-independent
  function/navigation keys via the new **`_named_keys()`** table; single
  characters (and the `plus`/`minus` word-aliases) via the layout char map;
  falling back to the old US `_tables()` only when xkbcommon is missing. A
  character not producible on the layout is warned about and skipped instead of
  crashing.
- The resolved shape dropped the `needs_shift` bool for a general
  `(all_mod_keycodes, keycode, is_combo)`, so **`press()`** emits modifiers +
  key uniformly and AltGr characters work too.

### Dependency (`environment.yml`)

Added `xkbcommon>=1.0` as a Linux-only pip dependency
(`sys_platform == 'linux'`); it wraps libxkbcommon, already present on Linux
desktops.

### Helper

`helpers/show_layout.py` prints the detected layout and how every configured
button resolves (keycode + modifiers), for quick verification without hardware.

## Result

On the Spanish layout, `PLUS = "+"` now resolves to `KEY_RIGHTBRACE` (no
modifier) and `MINUS = "-"` to `KEY_SLASH` — the real ES positions for those
characters. No `config.toml` change is required. If xkbcommon can't be loaded,
the bridge falls back to the previous US behavior with a warning.
