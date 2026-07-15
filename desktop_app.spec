# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация одного Windows .exe (Фаза 10 плана).

Сборка:  pyinstaller desktop_app.spec
Результат: dist/GarminHealthPipeline/GarminHealthPipeline.exe (+ соседние файлы)

Не --onefile: для FastAPI/uvicorn/telegram/pandas/curl_cffi однофайловая
сборка сильно увеличивает время старта (распаковка во временную папку при
каждом запуске) без реальной выгоды для десктоп-инструмента, который не
скачивают "разово" - --onedir быстрее стартует и проще диагностировать.
"""

from PyInstaller.utils.hooks import collect_all

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

# curl_cffi (garminconnect) и telegram грузят биб-ки/ресурсы динамически -
# collect_all надёжнее точечных hiddenimports.
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
    console=True,
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
