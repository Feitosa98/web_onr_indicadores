# -*- mode: python ; coding: utf-8 -*-


datas = [('templates', 'templates'), ('static', 'static'), ('imoveis_web.py', '.')]
binaries = []
hiddenimports = ['imoveis_web', 'iago', 'waitress', 'pystray', 'PIL', 'PIL._tkinter_finder', 'dotenv', 'psycopg2', 'engineio.async_drivers.threading', 'flask_wtf', 'flask_wtf.csrf', 'wtforms']

# Manual inclusion of problematic packages
import os
site_packages = os.path.join(os.getcwd(), '.venv', 'Lib', 'site-packages')
if os.path.exists(site_packages):
    # Add flask_wtf
    fwtf_path = os.path.join(site_packages, 'flask_wtf')
    if os.path.exists(fwtf_path):
        datas.append((fwtf_path, 'flask_wtf'))
    
    # Add wtforms
    wtforms_path = os.path.join(site_packages, 'wtforms')
    if os.path.exists(wtforms_path):
        datas.append((wtforms_path, 'wtforms'))

    # Add waitress
    waitress_path = os.path.join(site_packages, 'waitress')
    if os.path.exists(waitress_path):
        datas.append((waitress_path, 'waitress'))

a = Analysis(
    ['server_gui.py'],
    pathex=[site_packages], # Add site-packages to pathex explicitly
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
