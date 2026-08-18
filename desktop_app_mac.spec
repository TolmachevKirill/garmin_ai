# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация macOS .app-бандла.

PyInstaller не кросс-компилирует - собрать это можно ТОЛЬКО на самой macOS.
Разработка идёт на Windows, поэтому эта сборка гоняется на GitHub Actions
macOS-раннерах (.github/workflows/build-macos.yml), а не руками локально,
как desktop_app.spec для Windows.

Сборка (на маке или в CI):  pyinstaller desktop_app_mac.spec
Результат: dist/GarminHealthPipeline.app

Отличия от desktop_app.spec (Windows):
- console=False - обычное поведение "фонового" mac-приложения без терминала
  (логи всё ещё можно посмотреть, запустив бинарник внутри .app из Terminal);
- добавлен BUNDLE() с иконкой и Info.plist - без него получился бы просто
  голый исполняемый файл, а не нормальное приложение для Dock/Finder;
- icon.icns собирается в CI из packaging/mac-icon.png через sips/iconutil -
  сам .icns не хранится в git, т.к. это бинарный производный артефакт.
"""

import os

from PyInstaller.utils.hooks import collect_all

# Прокидывается из workflow (тег релиза) - используется только в Info.plist,
# на работу приложения не влияет.
APP_VERSION = os.environ.get("APP_VERSION", "0.0.0-dev")

datas = []
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

for pkg in ("curl_cffi", "telegram", "garminconnect", "fitdecode"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["desktop_app.py"],
    pathex=[],
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
    [],
    exclude_binaries=True,
    name="GarminHealthPipeline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GarminHealthPipeline",
)

app = BUNDLE(
    coll,
    name="GarminHealthPipeline.app",
    icon="icon.icns",
    bundle_identifier="ru.tolmachevkirill.garminhealthpipeline",
    info_plist={
        "CFBundleName": "Garmin Health Pipeline",
        "CFBundleDisplayName": "Garmin Health Pipeline",
        "CFBundleShortVersionString": APP_VERSION,
        "NSHighResolutionCapable": True,
        # Обычная страница браузера, не Cocoa-UI - Dock-иконка не нужна поверх
        # окна браузера, но сам процесс должен продолжать жить в фоне.
        "LSUIElement": False,
    },
)
