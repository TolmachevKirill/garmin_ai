<#
.SYNOPSIS
    Регистрирует задачу Windows Task Scheduler, которая раз в неделю запускает
    `python -m garmin_pipeline.cli weekly` и пишет отчёт в data/library/weekly.

.EXAMPLE
    # По умолчанию - каждое воскресенье в 21:00
    .\scripts\register_weekly_task.ps1

.EXAMPLE
    # Другой день/время
    .\scripts\register_weekly_task.ps1 -DayOfWeek Monday -Time "07:30"
#>

param(
    [string]$TaskName = "GarminHealthPipeline_Weekly",
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "21:00"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python).Source }

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m garmin_pipeline.cli weekly" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $Time

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Еженедельный сбор Garmin-метрик в библиотеку для ChatGPT Project" |
    Out-Null

Write-Host "Задача '$TaskName' зарегистрирована: каждое $DayOfWeek в $Time."
Write-Host "Python: $PythonExe"
Write-Host "Рабочая директория: $ProjectRoot"
Write-Host ""
Write-Host "Проверить: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Запустить вручную сейчас: Start-ScheduledTask -TaskName $TaskName"
