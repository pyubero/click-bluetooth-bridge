"""Shared BLE scanner, auto-discovery, and controller identification."""

import asyncio
import logging
import re

from bleak import BleakScanner, BleakClient

from .protocol import DIS, NAME_HINT, SERVICE_UUIDS, read_text

log = logging.getLogger("click_bridge")

# The DIS serial prefix identifies a controller's layout so the matching config
# block (by name) gets bound to it. Both units share the same serial suffix;
# only the prefix differs. Unknown prefixes fall back to asking the user.
SERIAL_PREFIX_TO_NAME = {"0A": "abyz", "0B": "dpad"}


class Discovery:
    def __init__(self, registry):
        self.registry = registry
        self.devices = {}                    # MAC -> BLEDevice (Click only)
        self._events = {}                    # MAC -> asyncio.Event
        self._new = asyncio.Event()          # fires when a new Click MAC appears
        self._scanner = BleakScanner(detection_callback=self._detected)

    @staticmethod
    def _is_click(device, adv):
        name = (getattr(device, "name", None) or getattr(adv, "local_name", None) or "")
        if NAME_HINT in name.lower():
            return True
        uuids = {u.lower() for u in (adv.service_uuids or [])}
        return bool(uuids & SERVICE_UUIDS)

    def _detected(self, device, adv):
        if not self._is_click(device, adv):
            return
        mac = device.address.upper()
        is_new = mac not in self.devices
        self.devices[mac] = device
        self.registry.record_sighting(mac, getattr(device, "name", None) or "Click Controller")
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
        """Return a Click MAC not in `exclude` (waits until one appears)."""
        while True:
            for mac in self.devices:
                if mac not in exclude:
                    return mac
            self._new.clear()
            await self._new.wait()


async def read_serial(device):
    """Briefly connect to read the DIS serial. Returns the string or None."""
    if device is None:
        return None
    try:
        async with BleakClient(device) as client:
            return await read_text(client, DIS["serial"])
    except Exception as e:
        log.warning("could not read serial from %s: %s", device.address, e)
        return None


async def identify_prefix(discovery, registry, mac):
    """Return the serial prefix (e.g. "0A") for a discovered MAC, or None.

    Uses the cached serial from devices.json when present; otherwise opens a
    short-lived connection to read it and persists the result.
    """
    serial = registry.data.get(mac, {}).get("serial")
    if not serial:
        serial = await read_serial(discovery.devices.get(mac))
        if serial:
            registry.record_details(mac, {"serial": serial})
    if serial and "-" in serial:
        return serial.split("-", 1)[0].upper()
    return None


def ask_block(mac, prefix, names):
    """Prompt the user to pick which config block a controller belongs to."""
    print(f"Discovered controller {mac} (serial prefix {prefix or 'unknown'}).")
    print("Which controller is this?")
    for i, n in enumerate(names, 1):
        print(f"  {i}) {n}")
    while True:
        ans = input("Enter number or name: ").strip()
        if ans in names:
            return ans
        if ans.isdigit() and 1 <= int(ans) <= len(names):
            return names[int(ans) - 1]
        print("Invalid choice.")


async def assign_auto_slots(discovery, registry, auto_blocks, claimed):
    """Resolve address-less config blocks to concrete MACs by serial identity.

    Returns {block_name: mac}. Routes each controller to the config block whose
    name matches its serial prefix; an unrecognized prefix (or one mapping to a
    non-auto/already-filled block) falls back to asking the user.
    """
    pending = {c["name"] for c in auto_blocks}
    result = {}
    while pending:
        mac = await discovery.claim_next(claimed)
        prefix = await identify_prefix(discovery, registry, mac)
        target = SERIAL_PREFIX_TO_NAME.get(prefix)
        if target not in pending:
            target = ask_block(mac, prefix, sorted(pending))
        claimed.add(mac)
        pending.discard(target)
        result[target] = mac
        log.info("[%s] assigned -> %s (serial prefix %s)", target, mac, prefix or "unknown")
    return result


def write_addresses(config_path, assignments):
    """Insert `address = "MAC"` under each matching [[controller]] block.

    A targeted textual edit that preserves comments (tomllib is read-only). Only
    touches a block with a matching name and no existing address, so re-running
    stays idempotent.
    """
    lines = config_path.read_text().splitlines(keepends=True)

    # split into segments, each starting at a [[controller]] header (index 0 is
    # the preamble before the first block)
    segments, cur = [], []
    for line in lines:
        if line.strip().startswith("[[controller]]") and cur:
            segments.append(cur)
            cur = []
        cur.append(line)
    segments.append(cur)

    out = []
    for seg in segments:
        name = next((m.group(1) for line in seg
                     if (m := re.match(r'\s*name\s*=\s*"([^"]*)"', line))), None)
        has_address = any(line.strip().startswith("address") for line in seg)
        if name in assignments and not has_address:
            for line in seg:
                out.append(line)
                if re.match(r'\s*name\s*=', line):
                    out.append(f'address = "{assignments[name]}"\n')
        else:
            out.extend(seg)
    config_path.write_text("".join(out))
    log.info("Updated config.toml with discovered addresses "
             "(remove an address = line to re-run discovery for that controller).")
