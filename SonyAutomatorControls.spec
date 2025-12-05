# -*- mode: python ; coding: utf-8 -*-
import os
import sys

try:
    from PyInstaller.building.build_main import Analysis
    from PyInstaller.building.api import EXE, PYZ
except ImportError:
    from PyInstaller.building.api import Analysis, EXE, PYZ

# Get version from package
sys.path.insert(0, os.path.abspath('.'))
try:
    from sony_automator_controls import __version__
    VERSION = __version__
except:
    VERSION = "1.0.0"

# Build data files list
datas = []
if os.path.exists('static'):
    datas.append(('static', 'static'))
if os.path.exists('README.md'):
    datas.append(('README.md', '.'))

a = Analysis(
    ['sony_automator_controls/__main__.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'tkinter',
        'tkinter.scrolledtext',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f'SonyAutomatorControls-{VERSION}',
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
    icon='static/sac_icon.ico',
)
