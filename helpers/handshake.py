import asyncio
import time
from bleak import BleakScanner, BleakClient

# ADDRESS = "F4:C4:59:03:BC:6F"  # the one with ABYZ+
ADDRESS = "F4:C4:59:03:A0:F3" # the one with up/down-

# Click service characteristics (base ...19ca-4651-86e5-fa29dcdd09d1)
CONTROL_POINT = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: handshake/commands
RESPONSE      = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate: handshake reply
MEASURED      = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify: button data

HANDSHAKE = b"RideOn"

t0 = time.monotonic()

def stamp():
    return f"{time.monotonic() - t0:7.3f}s"

def show(label, sender, data: bytearray):
    # Try to render printable ASCII alongside the hex, for readability.
    ascii_preview = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    print(f"[{stamp()}] {label:9} len={len(data):2}  hex={data.hex(' ')}  ascii={ascii_preview!r}")

async def main():
    print("Scanning... (press a button to wake the Click if needed)")
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20.0)
    if device is None:
        print(f"Could not find {ADDRESS}. Press a button and retry.")
        return

    print(f"Found {device.name}. Connecting...")
    async with BleakClient(device) as client:
        print(f"Connected: {client.is_connected}\n")

        def on_response(sender, data):
            show("RESPONSE", sender, data)

        def on_measured(sender, data):
            show("MEASURED", sender, data)

        await client.start_notify(RESPONSE, on_response)
        await client.start_notify(MEASURED, on_measured)

        print(f"[{stamp()}] Writing handshake {HANDSHAKE!r} to control point...\n")
        await client.write_gatt_char(CONTROL_POINT, HANDSHAKE, response=False)

        print("Now PRESS BOTH BUTTONS a few times, separately and together.")
        print("Watch for a repeating 1-byte idle message (~1 Hz) and longer press messages.")
        print("Listening for 60 seconds...\n")
        await asyncio.sleep(60)

        await client.stop_notify(RESPONSE)
        await client.stop_notify(MEASURED)
        print(f"\n[{stamp()}] Done.")

asyncio.run(main())


# Scanning... (press a button to wake the Click if needed)
# Found Click controller. Connecting...
# Connected: True

# [ 16.619s] Writing handshake b'RideOn' to control point...

# Now PRESS BOTH BUTTONS a few times, separately and together.
# Watch for a repeating 1-byte idle message (~1 Hz) and longer press messages.
# Listening for 60 seconds...

# [ 17.008s] RESPONSE  len= 6  hex=52 69 64 65 4f 6e  ascii='RideOn'
# [ 20.008s] MEASURED  len=23  hex=2a 08 03 12 12 12 10 08 24 10 00 18 d8 04 22 05 ff ff ff ff 1f 28 00  ascii='*.......$....."......(.'
# # pressed "A"
# [ 23.563s] MEASURED  len= 7  hex=23 08 ef ff ff ff 0f  ascii='#......'
# [ 23.651s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 23.788s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 23.878s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 23.968s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 24.058s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 24.193s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 24.283s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 24.373s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 24.508s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 24.598s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# # pressed "B"
# [ 29.953s] MEASURED  len= 7  hex=23 08 df ff ff ff 0f  ascii='#......'
# [ 30.043s] MEASURED  len= 7  hex=23 08 df ff ff ff 0f  ascii='#......'
# [ 30.178s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.268s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.358s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.492s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.583s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.673s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.763s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.898s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 30.988s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 31.078s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# # pressed "Z"
# [ 35.353s] MEASURED  len= 7  hex=23 08 ff fe ff ff 0f  ascii='#......'
# [ 35.443s] MEASURED  len= 7  hex=23 08 ff fe ff ff 0f  ascii='#......'
# [ 35.533s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 35.666s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 35.756s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 35.846s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 35.982s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 36.073s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 36.163s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 36.253s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 36.388s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 36.476s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# # pressed "Y"
# [ 40.393s] MEASURED  len= 7  hex=23 08 bf ff ff ff 0f  ascii='#......'
# [ 40.528s] MEASURED  len= 7  hex=23 08 bf ff ff ff 0f  ascii='#......'
# [ 40.618s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 40.708s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 40.843s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 40.933s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 41.023s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 41.113s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 41.248s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 41.338s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 41.428s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 41.563s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# # pressed button "+"
# [ 54.343s] MEASURED  len= 7  hex=23 08 ff df ff ff 0f  ascii='#......'
# [ 54.433s] MEASURED  len= 7  hex=23 08 ff df ff ff 0f  ascii='#......'
# [ 54.523s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 54.659s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 54.749s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 54.838s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 54.929s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 55.063s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 55.153s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 55.244s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 55.379s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'
# [ 55.469s] MEASURED  len= 7  hex=23 08 ff ff ff ff 0f  ascii='#......'

# ======================= SECOND CONTROLLER =======================
# (click-bridge) pablo@pablo-15ICH:~/Documentos/bt-driver$ python handshake.py
# Scanning... (press a button to wake the Click if needed)
# Found Click controller. Connecting...
# Connected: True

# [ 22.099s] Writing handshake b'RideOn' to control point...

# Now PRESS BOTH BUTTONS a few times, separately and together.
# Watch for a repeating 1-byte idle message (~1 Hz) and longer press messages.
# Listening for 60 seconds...

# [ 22.189s] RESPONSE  len= 6  hex=52 69 64 65 4f 6e  ascii='RideOn'
# [ 22.684s] MEASURED  len=23  hex=2a 08 03 12 12 12 10 08 24 10 00 18 d8 04 22 05 ff ff ff ff 1f 28 00  ascii='*.......$....."......(.'
# [ 22.685s] MEASURED  len=30  hex=ff 05 00 fa 05 18 0a 0c 33 34 43 34 35 39 30 33 41 30 46 33 20 64 28 ff 01 30 af 16 38 00  ascii='........34C45903A0F3 d(..0..8.'
# [ 24.574s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# [ 24.575s] MEASURED  len=31  hex=ff 05 00 ea 05 19 0a 0c 33 34 43 34 35 39 30 33 41 30 46 33 10 00 18 96 0c 20 00 28 04 30 00  ascii='........34C45903A0F3..... .(.0.'
# [ 26.869s] MEASURED  len=85  hex=ff 03 00 0a 21 02 1f 3c 23 f5 06 aa f2 98 60 77 2c b0 a1 7e bd 4d 43 21 16 2c 5a 94 a1 47 ff ac 4d 58 60 e3 79 96 10 80 80 8c 10 1a 28 7c 38 21 2e 7d 2e 39 1d b9 9e 7e d4 54 e7 ad ae 40 83 2d 76 4b e5 dd 1c f4 5d 4d 9a f2 c2 e9 6c fc 5c c7 19 c7 74 a5 d6  ascii='....!..<#.....`w,..~.MC!.,Z..G..MX`.y.......(|8!.}.9...~.T...@.-vK....]M....l.\\...t..'
# [ 30.919s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# # PRESSED UP
# [ 35.599s] MEASURED  len= 7  hex=23 08 fd ff ff ff 0f  ascii='#......'
# [ 35.689s] MEASURED  len= 7  hex=23 08 fd ff ff ff 0f  ascii='#......'
# [ 35.824s] MEASURED  len= 7  hex=23 08 fd ff ff ff 0f  ascii='#......'
# [ 35.914s] MEASURED  len= 7  hex=23 08 fd ff ff ff 0f  ascii='#......'
# [ 36.004s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# # PRESSED RIGHT
# [ 41.089s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# [ 41.179s] MEASURED  len= 7  hex=23 08 fb ff ff ff 0f  ascii='#......'
# [ 41.314s] MEASURED  len= 7  hex=23 08 fb ff ff ff 0f  ascii='#......'
# [ 41.404s] MEASURED  len= 7  hex=23 08 fb ff ff ff 0f  ascii='#......'
# [ 41.494s] MEASURED  len= 7  hex=23 08 fb ff ff ff 0f  ascii='#......'
# [ 46.174s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# # PRESSED DOWN
# [ 47.074s] MEASURED  len= 7  hex=23 08 f7 ff ff ff 0f  ascii='#......'
# [ 47.164s] MEASURED  len= 7  hex=23 08 f7 ff ff ff 0f  ascii='#......'
# [ 47.254s] MEASURED  len= 7  hex=23 08 f7 ff ff ff 0f  ascii='#......'
# [ 47.389s] MEASURED  len= 7  hex=23 08 f7 ff ff ff 0f  ascii='#......'
# [ 51.259s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# # PRESSED LEFT
# [ 52.789s] MEASURED  len= 7  hex=23 08 fe ff ff ff 0f  ascii='#......'
# [ 52.879s] MEASURED  len= 7  hex=23 08 fe ff ff ff 0f  ascii='#......'
# [ 52.969s] MEASURED  len= 7  hex=23 08 fe ff ff ff 0f  ascii='#......'
# [ 53.059s] MEASURED  len= 7  hex=23 08 fe ff ff ff 0f  ascii='#......'
# [ 56.344s] MEASURED  len= 3  hex=19 10 64  ascii='..d'
# # PRESSED MINUS
# [ 58.234s] MEASURED  len= 7  hex=23 08 ff fd ff ff 0f  ascii='#......'
# [ 58.324s] MEASURED  len= 7  hex=23 08 ff fd ff ff 0f  ascii='#......'
# [ 58.459s] MEASURED  len= 7  hex=23 08 ff fd ff ff 0f  ascii='#......'
# [ 58.549s] MEASURED  len= 7  hex=23 08 ff fd ff ff 0f  ascii='#......'
