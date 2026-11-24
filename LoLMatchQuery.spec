# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：pyinstaller --noconfirm LoLMatchQuery.spec
from PyInstaller.utils.hooks import collect_all

datas = [('src/lol_match_query/assets/app_icon.ico', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# MatchMonitorService 在运行时延迟创建传输层，显式告知 PyInstaller
hiddenimports += [
    'lol_match_query.lcu.client',
    'lol_match_query.lcu.connection',
]


a = Analysis(
    ['src/lol_match_query/app.py'],
    pathex=['src'],
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
    name='LoLMatchQuery',
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
    icon=['src/lol_match_query/assets/app_icon.ico'],
)
