# Sleeping controller "won't turn on" — clear stale BlueZ bond on reconnect

## Problem

A Zwift Click sleeps aggressively to save its coin cell. On Linux/BlueZ, if the
Click sleeps while BlueZ still holds it as a known/connected device, the Click
**stops re-advertising**. The shared scanner (`Discovery`) only reacts to fresh
advertisements (`_detected` → `wait_for(address)`), so the device is never
re-detected: `run_device` hangs at *"waiting for device"* and the controller
looks like it *"won't even turn on."*

This is a BlueZ state-management problem, not a device fault — the app never
sends any harmful write (the only characteristic write anywhere is the benign
`RideOn` handshake). The confirmed manual cure was `bluetoothctl remove <mac>`,
which purges BlueZ's cached device/bond and forces a fresh discovery on the next
button press.

## Fix

Automate that `remove` in code. `bleak`'s `BleakClient(address).unpair()` calls
`Adapter1.RemoveDevice(device_path)` on the BlueZ backend — exactly the manual
command. It raises `BleakDeviceNotFoundError` when the device isn't cached, so it
is safe to call unconditionally as best-effort.

### Code (`click_to_keys.py`)

- **`forget_device(address)`** — Linux-only, best-effort helper wrapping
  `BleakClient(address).unpair()` in `asyncio.wait_for(..., timeout=5)` (guards
  against a D-Bus hang during shutdown). Unknown devices and errors are swallowed.
- **Startup heal** — in `main()`, before `async with Discovery`, call
  `forget_device` for each fixed-address controller. This always runs, so it also
  recovers from a crash / `kill -9` / power loss. Auto-discovered slots are
  skipped: they resolve from a fresh advertisement this session and can't be stale.
- **Clean-shutdown tidy** — in `main()`'s `finally`, call `forget_device` for
  every resolved address so BlueZ is left clean on a normal exit. By the time
  `gather` returns (including Ctrl+C cancellation), each `run_device`'s
  `async with BleakClient` has already disconnected, so RemoveDevice runs on a
  cleanly-disconnected device. (Skipped on hard kill — the startup heal is the
  guaranteed-recovery half.)

## Verify

Real-world, button-by-button on both units (the only meaningful high-level test):

1. Connect both controllers, let one sleep (or `Ctrl+C` and relaunch).
2. On relaunch, confirm `cleared stale Bluetooth state for <mac>` prints before
   "waiting for device", and pressing a button on the previously-stuck controller
   reconnects and injects keys.
3. On `Ctrl+C`, confirm the same cleared-state lines print and `bluetoothctl
   devices` no longer lists the controllers.
