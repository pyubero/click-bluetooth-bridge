import asyncio
from bleak import BleakScanner, BleakClient

ADDRESS = "F4:C4:59:03:BC:6F"  # one of your two Clicks

async def main():
    print("Scanning...")
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20.0)
    if device is None:
        print(f"Could not find {ADDRESS}. Press a button on the Click to wake it, then retry.")
        return

    print(f"Found {device.name} ({device.address}). Connecting...")
    async with BleakClient(device) as client:
        print(f"Connected: {client.is_connected}\n")
        for service in client.services:
            print(f"[Service] {service.uuid}  {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"    [Char] {char.uuid}  ({props})  {char.description}")
        print("\nDone.")

asyncio.run(main())

# RESULTS:
# (zwift) pablo@pablo-15ICH:~/Documentos/bt-driver$ python discover.py 
# Scanning...
# Found Zwift Click (F4:C4:59:03:BC:6F). Connecting...
# Connected: True

# [Service] 0000180a-0000-1000-8000-00805f9b34fb  Device Information
#     [Char] 00002a29-0000-1000-8000-00805f9b34fb  (read)  Manufacturer Name String
#     [Char] 00002a25-0000-1000-8000-00805f9b34fb  (read)  Serial Number String
#     [Char] 00002a26-0000-1000-8000-00805f9b34fb  (read)  Firmware Revision String
#     [Char] 00002a27-0000-1000-8000-00805f9b34fb  (read)  Hardware Revision String
# [Service] 0000fc82-0000-1000-8000-00805f9b34fb  Vendor specific
#     [Char] 00000003-19ca-4651-86e5-fa29dcdd09d1  (write-without-response)  RFCOMM
#     [Char] 00000004-19ca-4651-86e5-fa29dcdd09d1  (read,indicate)  Unknown
#     [Char] 00000102-19ca-4651-86e5-fa29dcdd09d1  (write-without-response,notify)  Unknown
#     [Char] 00000002-19ca-4651-86e5-fa29dcdd09d1  (notify)  Unknown
#     [Char] 00000100-19ca-4651-86e5-fa29dcdd09d1  (write-without-response,write,notify)  L2CAP
#     [Char] 00000101-19ca-4651-86e5-fa29dcdd09d1  (write-without-response,write,notify)  Unknown
# [Service] 0000180f-0000-1000-8000-00805f9b34fb  Battery Service
#     [Char] 00002a19-0000-1000-8000-00805f9b34fb  (read,notify)  Battery Level
# [Service] 00001800-0000-1000-8000-00805f9b34fb  Generic Access Profile
#     [Char] 00002a01-0000-1000-8000-00805f9b34fb  (read,write)  Appearance
#     [Char] 00002ac9-0000-1000-8000-00805f9b34fb  (read)  Resolvable Private Address Only
#     [Char] 00002aa6-0000-1000-8000-00805f9b34fb  (read)  Central Address Resolution
#     [Char] 00002a00-0000-1000-8000-00805f9b34fb  (read,write)  Device Name
#     [Char] 00002a04-0000-1000-8000-00805f9b34fb  (read)  Peripheral Preferred Connection Parameters
# [Service] 00001801-0000-1000-8000-00805f9b34fb  Generic Attribute Profile
#     [Char] 00002a05-0000-1000-8000-00805f9b34fb  (indicate)  Service Changed

# Done.
