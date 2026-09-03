# PyInstaller spec for the portable Click controller -> keyboard bridge.
#
# Build locally with:   pyinstaller click-bridge.spec
# CI (.github/workflows/release.yml) runs this same spec on Windows and Linux to
# produce the two portable executables published on the Releases page.
#
# Onefile, console app. config.default.toml is bundled so the very first run can
# seed a config.toml next to the executable (see src/config.py). Runtime files
# (config.toml, devices.json, click_bridge.log) live beside the binary, not inside
# it, so each user edits their own copy.

import sys

from PyInstaller.utils.hooks import collect_submodules

# Bleak loads its OS backend (BlueZ / WinRT) dynamically, so its submodules are
# invisible to static analysis -- pull them in explicitly.
hiddenimports = collect_submodules("bleak")
if sys.platform == "linux":
    # Linux BLE goes through dbus-fast; the prompt-free keyboard uses evdev.
    hiddenimports += collect_submodules("dbus_fast")
    hiddenimports += ["evdev"]

# Trim modules PyInstaller pulls in transitively but the bridge never uses, to
# keep the portable binary lightweight.
excludes = [
    "tkinter", "unittest", "pydoc", "pydoc_data", "test", "lib2to3",
    "xml.dom", "xml.sax", "pdb", "doctest",
]

a = Analysis(
    ["src/main.py"],
    pathex=["."],                       # so `from src.main import ...` resolves
    binaries=[],
    datas=[("config.default.toml", ".")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="click-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,                         # drop symbols (no-op on Windows)
    # UPX left OFF on purpose: it shrinks the binary but is a common trigger for
    # antivirus false positives, which we specifically want to avoid. Only enable
    # if size becomes a real problem.
    upx=False,
    runtime_tmpdir=None,
    console=True,
)
