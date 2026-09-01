import asyncio
import tomllib
from pathlib import Path

from bleak import BleakScanner, BleakClient

# Standard GATT characteristics (no Zwift handshake needed to read these).
DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
BATTERY     = "00002a19-0000-1000-8000-00805f9b34fb"
DIS = [
    ("Manufacturer", "00002a29-0000-1000-8000-00805f9b34fb"),
    ("Serial no.",   "00002a25-0000-1000-8000-00805f9b34fb"),
    ("Firmware",     "00002a26-0000-1000-8000-00805f9b34fb"),
    ("Hardware",     "00002a27-0000-1000-8000-00805f9b34fb"),
]


def controllers_from_config():
    path = Path(__file__).parent / "config.toml"
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    out = []
    for i, block in enumerate(cfg.get("controller", [])):
        out.append((block.get("name", f"controller{i + 1}"), block["address"]))
    return out


async def read_text(client, uuid):
    try:
        data = await client.read_gatt_char(uuid)
        return bytes(data).decode("utf-8", "replace").strip("\x00").strip()
    except Exception as e:
        return f"(unavailable: {e})"


async def info_for(name, address):
    print(f"\n=== {name}  [{address}] ===")
    device = await BleakScanner.find_device_by_address(address, timeout=20.0)
    if device is None:
        print("  not found - press a button to wake it and re-run")
        return

    async with BleakClient(device) as client:
        print(f"  Device name : {await read_text(client, DEVICE_NAME)}")
        for label, uuid in DIS:
            print(f"  {label:12}: {await read_text(client, uuid)}")
        try:
            batt = await client.read_gatt_char(BATTERY)
            print(f"  Battery     : {batt[0]}%")
        except Exception as e:
            print(f"  Battery     : (unavailable: {e})")


async def main():
    for name, address in controllers_from_config():
        try:
            await info_for(name, address)
        except Exception as e:
            print(f"  error: {e}")
    print()


if __name__ == "__main__":
    asyncio.run(main())