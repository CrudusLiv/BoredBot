#Requires -Version 5.1
<#
.SYNOPSIS
Registers the three Vesper background tasks in Windows Task Scheduler.

.DESCRIPTION
Idempotent: re-running replaces existing tasks instead of erroring. Also
migrates away any legacy secondbrain-* tasks and the retired Discord-based
vesper-heartbeat task from older installs -- the voice app's own heartbeat
(voice/heartbeat.py, running inside vesper-voice) is now the single
proactive system.

  vesper-reflect     Daily 08:00 KL
  vesper-index       Every 10 min, all day
  vesper-voice       At logon, restart on failure (long-running)

All tasks run as the current interactive user so Windows Toast notifications
surface on the desktop.

.EXAMPLE
  pwsh -ExecutionPolicy Bypass -File .claude\scripts\deploy\install_tasks.ps1
#>
[CmdletBinding()]
param(
    [string]$User = $env:USERNAME
)

$ErrorActionPreference = 'Stop'

# Register-ScheduledTask requires elevation even when registering as the
# current user. Fail fast with a clear message rather than half-registering.
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "ERROR: This script must be run from an elevated PowerShell." -ForegroundColor Red
    Write-Host "Right-click PowerShell -> 'Run as administrator', then re-run:" -ForegroundColor Red
    Write-Host "  pwsh -ExecutionPolicy Bypass -File $PSCommandPath" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$ProjectDir   = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$ScriptsDir   = Join-Path $ProjectDir '.claude\scripts'
$LogsDir      = Join-Path $ProjectDir '.claude\data\logs'
$VoiceLaunch   = Join-Path $PSScriptRoot 'start_voice.vbs'

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

# Resolve py launcher up front so the user sees the failure here, not deep
# inside a task that silently exits 9009.
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $py) {
    throw "py.exe not found on PATH. Install Python from python.org so the launcher is available."
}
$PyPath = $py.Source

# Common task settings: allow on battery, restart on failure, don't stop after
# arbitrary deadline. The Discord task uses a stricter restart policy below.
function New-CommonSettings {
    New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
}

function Register-Task {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [ciminstance[]]$Trigger,
        [Parameter(Mandatory)] [ciminstance]$Action,
        [Parameter(Mandatory)] [ciminstance]$Settings,
        [string]$Description
    )
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Write-Host "  replacing existing task: $Name"
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    } else {
        Write-Host "  creating new task: $Name"
    }
    Register-ScheduledTask `
        -TaskName $Name `
        -Trigger $Trigger `
        -Action $Action `
        -Settings $Settings `
        -Description $Description `
        -User $User `
        -RunLevel Limited | Out-Null
}

Write-Host "Installing Vesper scheduled tasks..."
Write-Host "  project: $ProjectDir"
Write-Host "  user:    $User"
Write-Host "  py:      $PyPath"
Write-Host ""

# Migrate legacy installs: stop and remove old secondbrain-* and the
# retired Discord-based vesper-heartbeat task names.
foreach ($legacy in (Get-ScheduledTask -TaskName 'secondbrain-*' -ErrorAction SilentlyContinue) +
                     (Get-ScheduledTask -TaskName 'vesper-heartbeat' -ErrorAction SilentlyContinue)) {
    Write-Host "  removing legacy task: $($legacy.TaskName)"
    Stop-ScheduledTask -TaskName $legacy.TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $legacy.TaskName -Confirm:$false
}

# ----- vesper-reflect: daily 08:00 KL -----
$reflectTrigger = New-ScheduledTaskTrigger -Daily -At '08:00'
$reflectAction = New-ScheduledTaskAction `
    -Execute $PyPath `
    -Argument "`"$ScriptsDir\memory_reflect.py`"" `
    -WorkingDirectory $ProjectDir
Register-Task `
    -Name 'vesper-reflect' `
    -Trigger $reflectTrigger `
    -Action $reflectAction `
    -Settings (New-CommonSettings) `
    -Description 'Second Brain daily reflection. Promotes durable items from yesterday daily log into MEMORY.md.'

# ----- vesper-index: every 10 min, all day -----
# [TimeSpan]::MaxValue serialises to an out-of-range ISO duration that Task
# Scheduler rejects. Use the same daily-trigger + copied-repetition pattern as
# the heartbeat: the daily re-trigger at midnight restarts the 24-hour window,
# so effectively every 10 min forever.
$idxRepeatSrc = New-ScheduledTaskTrigger -Once -At '00:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Hours 24)
$idxTrigger = New-ScheduledTaskTrigger -Daily -At '00:00'
$idxTrigger.Repetition = $idxRepeatSrc.Repetition
$IdxLaunch = Join-Path $PSScriptRoot 'run_index.vbs'
$idxAction = New-ScheduledTaskAction `
    -Execute 'wscript.exe' `
    -Argument "`"$IdxLaunch`"" `
    -WorkingDirectory $ProjectDir
Register-Task `
    -Name 'vesper-index' `
    -Trigger $idxTrigger `
    -Action $idxAction `
    -Settings (New-CommonSettings) `
    -Description 'Second Brain vector indexer. Re-embeds vault files whose hash changed since last run.'

# ----- vesper-voice: at logon, long-running, restart on failure -----
$voiceTrigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$voiceAction = New-ScheduledTaskAction `
    -Execute 'wscript.exe' `
    -Argument "`"$VoiceLaunch`"" `
    -WorkingDirectory $ProjectDir
$voiceSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)
Register-Task `
    -Name 'vesper-voice' `
    -Trigger $voiceTrigger `
    -Action $voiceAction `
    -Settings $voiceSettings `
    -Description 'Vesper voice assistant. Starts orb UI + wakeword listener at logon. Wrapper auto-restarts on crashes.'

Write-Host ""
Write-Host "Installed. Inspect with:"
Write-Host "  Get-ScheduledTask -TaskName 'vesper-*' | Format-Table TaskName,State,LastRunTime,NextRunTime"
Write-Host ""
Write-Host "Tail logs from:"
Write-Host "  $LogsDir"
