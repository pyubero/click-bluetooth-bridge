"""Per-controller runtime: button tracking and the reconnecting device loop."""

import asyncio
import logging
import sys

from bleak import BleakClient
from bleak.exc import BleakError

from .keyboard import make_keyboard
from .protocol import (
    BATTERY, BUTTONS, CONTROL_POINT, DEVICE_NAME, DIS, HANDSHAKE,
    MEASURED, RESPONSE, parse_button_mask, read_text,
)

log = logging.getLogger("click_bridge")

BATTERY_POLL_INTERVAL = 120.0   # seconds between battery reads
RETRY_DELAY = 3.0


class Tracker:
    """Turns raw button-mask changes into keyboard press/release calls."""

    NAME_TO_BIT = {name: bit for bit, name in BUTTONS.items()}

    def __init__(self, keyboard, label=""):
        self.kb = keyboard
        self.label = label
        self.pressed = 0
        self.owned_bits = 0
        self.bit_names = {}
        for name in keyboard.keymap:
            bit = self.NAME_TO_BIT.get(name)
            if bit is not None:
                self.owned_bits |= (1 << bit)
                self.bit_names[bit] = name

    def reset(self):
        self.pressed = 0

    def update(self, mask):
        # active-low mask: bit=0 means pressed, so invert before comparing.
        now = (~mask) & self.owned_bits
        newly_pressed = now & ~self.pressed
        newly_released = ~now & self.pressed & self.owned_bits
        self.pressed = now
        for bit, name in self.bit_names.items():
            if newly_pressed & (1 << bit):
                log.debug("%sPRESS   %s", self.label, name)
                self.kb.press(name)
            if newly_released & (1 << bit):
                log.debug("%sRELEASE %s", self.label, name)
                self.kb.release(name)


async def record_details(client, registry, address):
    details = {"name": await read_text(client, DEVICE_NAME)}
    for label, uuid in DIS.items():
        details[label] = await read_text(client, uuid)
    registry.record_details(address.upper(), details)


async def forget_device(address):
    """Best-effort: purge a controller from BlueZ so a stale bond can't block
    reconnection. A Click that sleeps while BlueZ still holds it stops
    advertising and our scanner never re-detects it; unpair (equivalent to
    `bluetoothctl remove`) forces a fresh discovery on the next button press.
    Linux-only; unknown devices and errors are ignored."""
    if not sys.platform.startswith("linux"):
        return
    try:
        await asyncio.wait_for(BleakClient(address).unpair(), timeout=5)
        log.info("cleared stale Bluetooth state for %s", address)
    except Exception:
        pass


async def run_device(discovery, registry, address, keymap, label=""):
    keyboard = make_keyboard(keymap)
    tracker = Tracker(keyboard, label=label)

    def on_measured(sender, data):
        mask = parse_button_mask(data)
        if mask is not None:
            tracker.update(mask)

    while True:
        try:
            log.info("%swaiting for device (press a button to wake it)...", label)
            device = await discovery.wait_for(address)

            loop = asyncio.get_running_loop()
            disconnected = asyncio.Event()

            def on_disconnect(_client):
                loop.call_soon_threadsafe(disconnected.set)

            log.info("%sconnecting...", label)
            async with BleakClient(device, disconnected_callback=on_disconnect) as client:
                tracker.reset()
                await client.start_notify(RESPONSE, lambda s, d: None)
                await client.start_notify(MEASURED, on_measured)
                await client.write_gatt_char(CONTROL_POINT, HANDSHAKE, response=False)
                await record_details(client, registry, address)
                log.info("%sready.", label)

                # battery: read now, then poll until disconnect (reads avoid the
                # multi-device notification cross-talk that notify would hit)
                last_batt = None
                while not disconnected.is_set():
                    try:
                        batt = (await client.read_gatt_char(BATTERY))[0]
                        if batt != last_batt:
                            log.info("%sbattery %d%%", label, batt)
                            last_batt = batt
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(disconnected.wait(), timeout=BATTERY_POLL_INTERVAL)
                    except asyncio.TimeoutError:
                        pass
                log.info("%sdisconnected.", label)
        except asyncio.CancelledError:
            keyboard.release_all()
            if hasattr(keyboard, "close"):
                keyboard.close()
            raise
        except (BleakError, asyncio.TimeoutError, EOFError, OSError) as e:
            log.warning("%sconnection error: %s", label, e)
        finally:
            keyboard.release_all()
        log.info("%sreconnecting in %.0fs...", label, RETRY_DELAY)
        await asyncio.sleep(RETRY_DELAY)
