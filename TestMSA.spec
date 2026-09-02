# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller : un unique TestMSA.exe, sans console."""

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["paramiko", "requests"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "numpy", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TestMSA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # application fenetree : pas de console noire
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
