import asyncio
from bleak import BleakScanner, BleakClient

ADDRESS = "F4:C4:59:03:BC:6F"  # one of your two Clicks

CONTROL_POINT = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: handshake
RESPONSE      = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate: handshake reply
MEASURED      = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify: button data

HANDSHAKE = b"RideOn"
BUTTON_MSG_TYPE = 0x23  # leading byte of a button-status message

# bit index (in the 32-bit active-low mask) -> button name
BUTTONS = {
    4:  "A",
    5:  "B",
    6:  "Y",
    7:  "Z",
    12: "PLUS",
    # press any unmapped button and this script will report its bit index
}


def read_varint(data, offset):
    """Read a protobuf base-128 varint. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, offset


def parse_button_mask(data: bytearray):
    """Return the 32-bit button mask from a button-status message, or None."""
    if not data or data[0] != BUTTON_MSG_TYPE:
        return None
    offset = 1
    mask = None
    # walk the protobuf fields; we only care about field 1 (the bitmask)
    while offset < len(data):
        tag = data[offset]
        offset += 1
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            value, offset = read_varint(data, offset)
            if field_num == 1:
                mask = value & 0xFFFFFFFF
        else:
            break  # anything else: stop (we don't need it)
    return mask


class ButtonTracker:
    def __init__(self):
        self.pressed = 0  # bits currently held (1 = pressed)

    def update(self, mask):
        now = (~mask) & 0xFFFFFFFF          # active-low -> 1 means pressed
        newly_pressed = now & ~self.pressed
        newly_released = ~now & self.pressed & 0xFFFFFFFF
        self.pressed = now
        for bit in range(32):
            name = BUTTONS.get(bit, f"bit{bit}")
            if newly_pressed & (1 << bit):
                print(f"PRESS   {name}")
            if newly_released & (1 << bit):
                print(f"RELEASE {name}")


async def main():
    print("Scanning... (press a button to wake the Click if needed)")
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20.0)
    if device is None:
        print(f"Could not find {ADDRESS}. Press a button and retry.")
        return

    print(f"Found {device.name}. Connecting...")
    async with BleakClient(device) as client:
        print(f"Connected: {client.is_connected}")
        tracker = ButtonTracker()

        def on_measured(sender, data):
            mask = parse_button_mask(data)
            if mask is not None:
                tracker.update(mask)

        await client.start_notify(RESPONSE, lambda s, d: None)
        await client.start_notify(MEASURED, on_measured)
        await client.write_gatt_char(CONTROL_POINT, HANDSHAKE, response=False)

        print("Ready. Press buttons (Ctrl+C to quit).\n")
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nBye.")


# Connected: True
# Ready. Press buttons (Ctrl+C to quit).

# PRESS   A
# RELEASE A
# PRESS   B
# RELEASE B
# PRESS   Z
# RELEASE Z
# PRESS   Y
# RELEASE Y
# PRESS   PLUS
# RELEASE PLUS
# PRESS   A
# PRESS   Y
# RELEASE A
# RELEASE Y
# PRESS   B
# PRESS   Y
# RELEASE B
# RELEASE Y
# PRESS   Y
# PRESS   Z
# RELEASE Y
# RELEASE Z
