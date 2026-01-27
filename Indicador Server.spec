# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('imoveis_web.py', '.')],
    hiddenimports=['imoveis_web', 'iago', 'waitress', 'pystray', 'PIL', 'PIL._tkinter_finder', 'dotenv', 'psycopg2', 'engineio.async_drivers.threading', 'flask_wtf', 'flask_wtf.csrf'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Indicador Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
