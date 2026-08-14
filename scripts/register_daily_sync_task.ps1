<#
.SYNOPSIS
    Регистрирует задачу Windows Task Scheduler, которая раз в день тихо
    синхронизирует локальный кэш (`python -m garmin_pipeline.cli sync`) -
    без записи файлов в библиотеку. Это то, что делает отчёты за произвольный
    период (веб-дашборд -> "Отчёт за период", CLI `range`) мгновенными: они
    читают уже засинканные дни из SQLite вместо похода в Garmin API при
    каждом запросе (см. collectors/range_report.py::build_range_report).

.EXAMPLE
    # По умолчанию - каждый день в 08:00, последние 3 дня
    .\scripts\register_daily_sync_task.ps1

.EXAMPLE
    # Другое время/глубина синка
    .\scripts\register_daily_sync_task.ps1 -Time "07:00" -Days 5
#>

param(
    [string]$TaskName = "GarminHealthPipeline_DailySync",
    [string]$Time = "08:00",
    [int]$Days = 3
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python).Source }

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m garmin_pipeline.cli sync --days $Days" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $Time

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Ежедневная фоновая синхронизация кэша Garmin-метрик (без записи файлов в библиотеку)" |
    Out-Null

Write-Host "Задача '$TaskName' зарегистрирована: каждый день в $Time, последние $Days дн."
Write-Host "Python: $PythonExe"
Write-Host "Рабочая директория: $ProjectRoot"
Write-Host ""
Write-Host "Проверить: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Запустить вручную сейчас: Start-ScheduledTask -TaskName $TaskName"
