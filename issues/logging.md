# Improve logging and export to a rotating logfile

## Problem

All runtime output went through bare `print()` (~30 sites in
`click_to_keys.py`). Nothing was persisted: once the terminal scrolled or the
process restarted, the connection history, battery readings, errors, and — most
importantly — the button-by-button PRESS/RELEASE trace (the project's primary
real-world test, per CLAUDE.md) were gone.

## Fix

Route runtime output through the stdlib `logging` module and add a size-rotating
logfile `click_bridge.log` next to the script. The console keeps its familiar
plain look; the logfile always captures full detail, button events included.

### Code (`click_to_keys.py`)

- **`LOG_PATH = Path(__file__).parent / "click_bridge.log"`** — constant beside
  `REGISTRY_PATH` / `CONFIG_PATH`.
- **`log = logging.getLogger("click_bridge")`** — module logger used everywhere.
- **`setup_logging(verbose)`** — configures two handlers (idempotent: returns if
  already configured). The logger itself is DEBUG with `propagate = False`.
  - **File:** `RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3,
    encoding="utf-8")` at DEBUG, format
    `"%(asctime)s %(levelname)-7s %(message)s"` (datefmt `%Y-%m-%d %H:%M:%S`).
  - **Console:** `StreamHandler(sys.stdout)`, INFO by default / DEBUG with `-v`,
    format `"%(message)s"` — no timestamps, preserving the old console look. The
    `[name] ` label already embedded in each message keeps per-controller
    attribution.
- **`-v/--verbose`** CLI flag (argparse in `__main__`) — raises console
  verbosity to DEBUG so button events show live. The logfile is DEBUG
  regardless. `setup_logging(args.verbose)` runs before `asyncio.run(main())`.
- **`print()` → `log.*`** substitutions by level:
  - **DEBUG:** `Tracker.update` PRESS/RELEASE (high-frequency; file-only unless
    `-v`).
  - **INFO:** normal status — waiting/connecting/ready/battery/disconnected/
    reconnecting, "Loaded N controller(s)", "discovering…", auto-assign lines,
    the config write-back confirmation, the uinput "Injecting via…" notice, and
    "cleared stale Bluetooth state".
  - **WARNING:** recoverable problems — registry write failure, serial read
    failure, connection errors, and the uinput-unavailable / not-writable
    fallback notices.
- **Left as `print()` / `input()`:** the `ask_block()` interactive menu+prompt
  (not a log event; timestamps would clutter a live prompt) and the final
  `"\nBye."` console farewell on `KeyboardInterrupt`.

## Scope / notes

- `.gitignore` already ignores `*.log`, so `click_bridge.log` and its rotation
  backups (`click_bridge.log.1`…`.3`) are untracked automatically.
- Size-based rotation (1 MB × 3 backups ≈ 4 MB cap) was chosen over time-based;
  the logfile's growth is dominated by button events, so size is the natural
  bound.
- Helper scripts under `helpers/` are standalone and were left on `print()`.
