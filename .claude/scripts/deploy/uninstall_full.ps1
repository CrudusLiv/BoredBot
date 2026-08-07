# Full uninstall — stops everything and disables all auto-start.
# Does NOT delete any files.
#
# Run from project root:
#   .claude\scripts\deploy\uninstall_full.ps1

$ProjectDir = $PSScriptRoot | Split-Path -Parent | Split-Path -Parent | Split-Path -Parent
$PidFile    = Join-Path $ProjectDir '.claude\data\bot.pid'

# 1. Quit the tray app if running
$trayProcs = Get-Process -Name pythonw -ErrorAction SilentlyContinue
if ($trayProcs) {
    $trayProcs | Stop-Process -Force
    Write-Host "Stopped tray app."
} else {
    Write-Host "Tray app not running."
}

# 2. Stop the bot process tree via PID file
if (Test-Path $PidFile) {
    $pid = [int](Get-Content $PidFile -Raw).Trim()
    try {
        $proc = Get-Process -Id $pid -ErrorAction Stop
        $children = (Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $pid })
        $proc | Stop-Process -Force
        $children | ForEach-Object {
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
        Write-Host "Stopped bot process tree (PID $pid)."
    } catch {
        Write-Host "Bot process (PID $pid) not running."
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "No bot.pid found — bot not running."
}

# 3. Remove startup registry entry
$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
try {
    Remove-ItemProperty -Path $regPath -Name 'VesperTray' -ErrorAction Stop
    Write-Host "Removed VesperTray startup entry."
} catch {
    Write-Host "VesperTray startup entry not found — skipping."
}

# 4. Disable the discord bot Task Scheduler task
$discordTask = Get-ScheduledTask -TaskName 'secondbrain-discord' -ErrorAction SilentlyContinue
if ($discordTask -and $discordTask.State -ne 'Disabled') {
    Disable-ScheduledTask -TaskName 'secondbrain-discord' | Out-Null
    Write-Host "Disabled Task Scheduler task: \secondbrain-discord"
} else {
    Write-Host "Task \secondbrain-discord already disabled or not found."
}

# 5. Disable the heartbeat Task Scheduler task
$hbTask = Get-ScheduledTask -TaskName 'secondbrain-heartbeat' -ErrorAction SilentlyContinue
if ($hbTask -and $hbTask.State -ne 'Disabled') {
    Disable-ScheduledTask -TaskName 'secondbrain-heartbeat' | Out-Null
    Write-Host "Disabled Task Scheduler task: \secondbrain-heartbeat"
} else {
    Write-Host "Task \secondbrain-heartbeat already disabled or not found."
}

Write-Host ""
Write-Host "Full uninstall complete. Nothing will start at logon."
Write-Host "To re-enable the bot only: schtasks /change /tn \secondbrain-discord /enable"
Write-Host "To re-enable heartbeat:    schtasks /change /tn \secondbrain-heartbeat /enable"
