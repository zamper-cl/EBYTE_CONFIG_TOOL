# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)

datas = [(str(ROOT / "docs" / "img" / "modo-config.jpeg"), "docs/img")]
binaries = []
hiddenimports = [
    "serial",
    "serial.tools.list_ports",
    "ebyte_dtu",
    "ebyte_dtu.window",
    "ebyte_dtu.e860_window",
    "ebyte_dtu.e860",
    "ebyte_dtu.protocol",
    "ebyte_dtu.serial_session",
    "ebyte_dtu.link",
]

qt_datas, qt_binaries, qt_hidden = collect_all("PyQt6")
datas += qt_datas
binaries += qt_binaries
hiddenimports += qt_hidden

a = Analysis(
    [str(ROOT / "ebyte_dtu" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ConfiguradorE95",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
