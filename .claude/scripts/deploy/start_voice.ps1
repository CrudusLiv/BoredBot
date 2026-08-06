#Requires -Version 5.1
<#
.SYNOPSIS
Long-running launcher for the Vesper voice assistant.

.DESCRIPTION
Task Scheduler runs this at logon. Restarts the voice app if it crashes
(fast crash loops are throttled). Logs to .claude/data/logs/voice-YYYY-MM-DD.log.

Two layers of restart resilience:
  1. This loop catches process exit and relaunches after a short backoff.
  2. Task Scheduler restarts the whole PowerShell process if this script
     itself dies (RestartCount=999, RestartInterval=1min in install_tasks.ps1).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

$ProjectDir = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$LogsDir    = Join-Path $ProjectDir '.claude\data\logs'
New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

# Retention: one log file per day accumulates forever otherwise. Runs once
# per launcher start (i.e. at logon), which is enough for a daily cadence.
$RetentionDays = 14
Get-ChildItem -Path $LogsDir -Filter 'voice-*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$py = (Get-Command py.exe -ErrorAction Stop).Source

# Tray "Stop until next logon" drops this sentinel just before exiting; we
# break the relaunch loop when we see it. A stale flag from a previous
# session must not block a fresh logon start, so clear it up front.
# (Path mirrors voice/config.get_data_dir() default: %APPDATA%\Vesper.)
$StopFlag = Join-Path $env:APPDATA 'Vesper\stop_voice.flag'
Remove-Item $StopFlag -Force -ErrorAction SilentlyContinue

$MinBackoff     = 5
$MaxBackoff     = 300
$FastFailWindow = 60
$backoff        = $MinBackoff

while ($true) {
    $logFile = Join-Path $LogsDir ("voice-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
    $stamp   = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $logFile -Value "[$stamp] launcher: starting voice app"

    $start = Get-Date
    try {
        & $py -u -m voice --voice 2>&1 | ForEach-Object {
            $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $_
            Add-Content -Path $logFile -Value $line
        }
        $exit = $LASTEXITCODE
    } catch {
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] launcher: exception $_"
        $exit = 1
    }

    $uptime = ((Get-Date) - $start).TotalSeconds
    $stamp  = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $logFile -Value ("[$stamp] launcher: voice exited code={0} uptime={1:N0}s" -f $exit, $uptime)

    if (Test-Path $StopFlag) {
        Remove-Item $StopFlag -Force -ErrorAction SilentlyContinue
        Add-Content -Path $logFile -Value "[$stamp] launcher: stop requested from tray - exiting until next logon"
        break
    }

    if ($uptime -lt $FastFailWindow) {
        $backoff = [Math]::Min($backoff * 2, $MaxBackoff)
        Add-Content -Path $logFile -Value "[$stamp] launcher: fast-fail, backoff=${backoff}s"
    } else {
        $backoff = $MinBackoff
    }

    Start-Sleep -Seconds $backoff
}
