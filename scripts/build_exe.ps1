<#
.SYNOPSIS
    Rebuilds the Windows .exe (desktop_app.spec) without losing local settings.

.DESCRIPTION
    PyInstaller's COLLECT step deletes and recreates dist/GarminHealthPipeline
    on every rebuild (visible in its log as "Removing dir ...") - including the
    data/ folder next to the .exe, where your own config.json, cache.sqlite3
    and tokens/ live if you've run the built .exe locally for testing (see
    garmin_pipeline/config.py::_detect_project_root).

    End users who download a release once and never rebuild the .exe
    themselves never hit this. But during local development, rebuilding would
    wipe your test Garmin/LLM/Telegram settings every time. This script backs
    up dist/GarminHealthPipeline/data before the build and restores it after -
    use it instead of a bare `pyinstaller desktop_app.spec` for local rebuilds.

.EXAMPLE
    .\scripts\build_exe.ps1
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$distData = Join-Path $root "dist\GarminHealthPipeline\data"
$backup = Join-Path $root "dist\_data_backup"

if (Test-Path $distData) {
    if (Test-Path $backup) {
        Remove-Item $backup -Recurse -Force
    }
    Copy-Item $distData $backup -Recurse
    Write-Host "Backed up dist/GarminHealthPipeline/data to $backup"
}

& "$root\.venv\Scripts\pyinstaller.exe" "$root\desktop_app.spec" --noconfirm

if (Test-Path $backup) {
    Copy-Item $backup $distData -Recurse -Force
    Remove-Item $backup -Recurse -Force
    Write-Host "Restored data/ after rebuild - your local settings are intact."
}

Write-Host "Done: $root\dist\GarminHealthPipeline\GarminHealthPipeline.exe"
