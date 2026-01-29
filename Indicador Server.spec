# -*- mode: python ; coding: utf-8 -*-


datas = [('templates', 'templates'), ('static', 'static'), ('imoveis_web.py', '.')]
binaries = []
hiddenimports = ['imoveis_web', 'iago', 'waitress', 'pystray', 'PIL', 'PIL._tkinter_finder', 'dotenv', 'psycopg2', 'engineio.async_drivers.threading', 'flask_wtf', 'flask_wtf.csrf', 'wtforms']

# Manual inclusion of problematic packages
import os
site_packages = os.path.join(os.getcwd(), '.venv', 'Lib', 'site-packages')
if os.path.exists(site_packages):
    # List of packages that frequently fail to Bundle
    packages_to_include = [
        'flask_wtf', 'wtforms', 'waitress', 'pystray', 'PIL', 
        'engineio', 'socketio', 'psycopg2', 'charset_normalizer',
        'requests', 'urllib3', 'idna', 'certifi', 'spacy', 
        'thinc', 'srsly', 'cymem', 'preshed', 'murmurhash', 'blis',
        'win32com', 'win32', 'pythoncom', 'pywintypes'
    ]

    for package in packages_to_include:
        pkg_path = os.path.join(site_packages, package)
        if os.path.exists(pkg_path):
            datas.append((pkg_path, package))
        else:
             # Try simple name or egg-info variations might be needed in severe cases
             # but usually direct mapping works for these.
             print(f"WARNING: Package path not found for manual include: {pkg_path}")

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
