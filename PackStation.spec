# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/i18n', 'i18n'), ('C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/audio', 'audio'), ('C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/assets', 'assets'), ('C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/libs', 'libs')]
binaries = [('C:/Users/doh52/AppData/Local/Python/pythoncore-3.14-64/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe', '.')]
hiddenimports = ['pyzbar', 'zxingcpp', 'customtkinter', 'PIL', 'cv2', 'openpyxl', 'certifi']
datas += collect_data_files('certifi')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyzbar')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('zxingcpp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/main.py'],
    pathex=[],
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
    [],
    exclude_binaries=True,
    name='PackStation',
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
    version='C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/version_info.txt',
    icon=['C:/Users/doh52/OneDrive/Máy tính/camsight/PackStation/assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PackStation',
)
