# Autodiscovery should know which controller is which (+ write config.toml back)

## Problem

Auto-discovery resolved each address-less `[[controller]]` block by calling
`Discovery.claim_next()`, which returns the **next Click MAC in arbitrary
discovery order**. With two controllers of different layouts (abyz vs dpad),
this routinely bound the wrong keymap to the wrong physical controller — the
`abyz` block could end up driving the d-pad unit.

The controllers are distinguishable by their **DIS serial prefix** (already
recorded in `devices.json`): `0A` = abyz, `0B` = d-pad. Both share the same
serial suffix; only the prefix differs.

> **Correction:** `ISSUES.md` originally stated `0A` = d-pad / `0B` = abyz, which
> is **inverted** relative to the real hardware. `helpers/decode_buttons.py`
> connects to `F4:C4:59:03:BC:6F` (serial `0A`) and its captured session shows
> **ABYZ** presses (bits 4–7,12), proving `0A` is the abyz controller. The first
> pass shipped the inverted table, so the `dpad` block was bound to an abyz
> device and emitted no key presses (its owned bits never changed). Fixed by
> flipping `SERIAL_PREFIX_TO_NAME` to `{"0A": "abyz", "0B": "dpad"}`.

## Fix

Identify each discovered controller by its serial prefix and route it to the
config block of the **matching name**. Read the serial from the `devices.json`
cache when present; otherwise open a short-lived connection to read it (so a
returning user pays no connect cost, and only a brand-new controller triggers
one). An unrecognized prefix falls back to asking the user. After a successful
discovery, write the resolved addresses back into `config.toml` so the next
launch is deterministic.

### Code (`click_to_keys.py`)

- **`SERIAL_PREFIX_TO_NAME = {"0A": "abyz", "0B": "dpad"}`** — prefix → block name.
- **`CONFIG_PATH`** module constant (also reused by `load_config()`).
- **`read_serial(device)`** — brief `BleakClient` connect to read `DIS["serial"]`
  via the existing `_read_text()`; returns `None` on any error.
- **`identify_prefix(discovery, registry, mac)`** — cache-first (uses the serial
  in `devices.json`), else connects to read + persists it via
  `registry.record_details`; returns the upper-cased prefix or `None`.
- **`ask_block(mac, prefix, names)`** — `input()` prompt listing the still-
  unassigned block names; used only when the prefix isn't 0A/0B.
- **`assign_auto_slots(discovery, registry, auto_blocks, claimed)`** — replaces
  the blind `claim_next` loop; returns `{block_name: mac}`, routing each
  discovered controller to the block of the matching name (or asking).
- **`write_addresses(config_path, assignments)`** — targeted textual edit that
  inserts `address = "MAC"` under each matching, address-less block. Preserves
  the file's comments (stdlib `tomllib` is read-only) and is idempotent — a
  block that already has an address is left untouched.
- **`main()`** — resolves auto slots via `assign_auto_slots`, then calls
  `write_addresses` once; builds `specs` in config order.

## Scope / notes

- The `--autodiscover` flag and the logging/logfile items in ISSUES.md are **not**
  part of this change. Without the flag, re-running discovery for a controller
  means deleting its `address =` line in `config.toml` (the write-back message
  says so).
- Matching is by block **name** (`dpad`/`abyz`); renaming a block means its
  prefix maps to a missing name and the tool asks instead.
