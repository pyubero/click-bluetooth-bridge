"""Zwift BLE protocol: characteristic UUIDs and button-message parsing."""

# Zwift service characteristics.
CONTROL_POINT = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: handshake
RESPONSE      = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate: handshake reply
MEASURED      = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify: button data
HANDSHAKE = b"RideOn"
BUTTON_MSG_TYPE = 0x23

# Standard characteristics.
BATTERY     = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
DIS = {  # human label -> Device Information Service characteristic
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "serial":       "00002a25-0000-1000-8000-00805f9b34fb",
    "firmware":     "00002a26-0000-1000-8000-00805f9b34fb",
    "hardware":     "00002a27-0000-1000-8000-00805f9b34fb",
}

# How auto-discovery recognises a Zwift controller.
ZWIFT_NAME_HINT = "zwift"
ZWIFT_SERVICE_UUIDS = {
    "0000fc82-0000-1000-8000-00805f9b34fb",   # newer firmware
    "00000001-19ca-4651-86e5-fa29dcdd09d1",   # older firmware
}

# bit index in the 32-bit active-low mask -> button name.
BUTTONS = {
    0: "LEFT", 1: "UP", 2: "RIGHT", 3: "DOWN", 8: "MINUS",   # d-pad + minus
    4: "A", 5: "B", 6: "Y", 7: "Z", 12: "PLUS",              # ABXY + plus
}


def read_varint(data, offset):
    result = shift = 0
    while True:
        b = data[offset]; offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, offset
        shift += 7


def parse_button_mask(data: bytearray):
    """Extract the 32-bit button mask from a 0x23 protobuf message, or None."""
    if not data or data[0] != BUTTON_MSG_TYPE:
        return None
    offset, mask = 1, None
    while offset < len(data):
        tag = data[offset]; offset += 1
        if (tag & 0x07) != 0:
            break
        value, offset = read_varint(data, offset)
        if (tag >> 3) == 1:
            mask = value & 0xFFFFFFFF
    return mask


async def read_text(client, uuid):
    """Read a GATT characteristic as a trimmed UTF-8 string, or None on error."""
    try:
        return bytes(await client.read_gatt_char(uuid)).decode("utf-8", "replace").strip("\x00").strip()
    except Exception:
        return None
