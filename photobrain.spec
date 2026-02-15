# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for PhotoBrain Desktop."""
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Collect mediapipe data files and dynamic libs
mediapipe_datas = collect_data_files('mediapipe')
mediapipe_libs = collect_dynamic_libs('mediapipe')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=mediapipe_libs,
    datas=[
        ('assets', 'assets'),
        *mediapipe_datas,
    ],
    hiddenimports=[
        'mediapipe',
        'mediapipe.tasks',
        'mediapipe.tasks.python',
        'mediapipe.tasks.python.vision',
        'mediapipe.tasks.python.core',
        'mediapipe.tasks.python.components',
        'mediapipe.python',
        'mediapipe.python._framework_bindings',
        'cv2',
        'numpy',
        'PIL',
        'imagehash',
        'send2trash',
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhotoBrain',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/photobrain.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhotoBrain',
)
