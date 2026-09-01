"""Entry point: config load, discovery orchestration, and per-device tasks."""

# Support `python src/main.py` (run as a loose script, no package context): put
# the repo root on the path and re-enter as a proper module so the relative
# imports below resolve. `python click_to_keys.py` and `python -m src.main`
# already have package context and skip this.
if __name__ == "__main__" and __package__ in (None, ""):
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from src.main import main_cli

    main_cli()
    raise SystemExit

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import CONFIG_PATH, LOG_PATH, REGISTRY_PATH, load_config
from .device import forget_device, run_device
from .discovery import Discovery, assign_auto_slots, write_addresses
from .registry import Registry

log = logging.getLogger("click_bridge")


def setup_logging(verbose: bool):
    """Route runtime output to a rotating logfile plus the console.

    The file handler is always DEBUG so click_bridge.log keeps the full
    button-by-button trace; the console is INFO by default (clean, no
    timestamps) and DEBUG when `verbose` is set.
    """
    if log.handlers:            # already configured
        return
    log.setLevel(logging.DEBUG)
    log.propagate = False

    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))

    log.addHandler(file_handler)
    log.addHandler(console)


async def main():
    controllers = load_config()
    registry = Registry(REGISTRY_PATH)

    fixed = [c for c in controllers if c["address"]]
    auto = [c for c in controllers if not c["address"]]
    log.info("Loaded %d controller(s): %s",
             len(controllers), ", ".join(c["name"] for c in controllers))
    if auto:
        log.info("%d will be auto-assigned to discovered Zwift controllers.", len(auto))

    # heal stale BlueZ bonds from a prior (possibly unclean) run before scanning,
    # so a sleeping controller at a known address can advertise & reconnect
    for c in fixed:
        await forget_device(c["address"])

    async with Discovery(registry) as discovery:
        claimed = {c["address"].upper() for c in fixed}
        assigned = {}
        if auto:
            log.info("discovering %d controller(s)...", len(auto))
            assigned = await assign_auto_slots(discovery, registry, auto, claimed)
            write_addresses(CONFIG_PATH, assigned)

        specs = []
        for c in controllers:
            addr = c["address"] or assigned[c["name"]]
            specs.append((c["name"], addr, c["keymap"]))

        addresses = [addr for _, addr, _ in specs]
        tasks = [
            asyncio.create_task(run_device(discovery, registry, addr, keymap, label=f"[{name}] "))
            for name, addr, keymap in specs
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            registry.flush()
            # leave BlueZ clean on a normal exit so the controllers reconnect
            # freshly next time (startup heal covers hard kills that skip this)
            for addr in addresses:
                await forget_device(addr)


def main_cli():
    parser = argparse.ArgumentParser(
        description="Bridge Zwift Click button presses to keyboard input."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="show DEBUG detail (button PRESS/RELEASE events) on the console; "
             f"the logfile ({LOG_PATH.name}) always keeps full detail.",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main_cli()
