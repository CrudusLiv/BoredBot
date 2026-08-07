#Requires -Version 5.1
<#
.SYNOPSIS
Removes all Vesper scheduled tasks.

.DESCRIPTION
Safe counterpart to install_tasks.ps1. Only touches tasks matching
'vesper-*' (plus legacy 'secondbrain-*' names from older installs) so nothing
else is at risk. Idempotent: re-running on a clean system is a no-op.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Run from an elevated PowerShell (Unregister-ScheduledTask requires admin)." -ForegroundColor Red
    exit 1
}

$tasks = @(Get-ScheduledTask -TaskName 'vesper-*' -ErrorAction SilentlyContinue) +
         @(Get-ScheduledTask -TaskName 'secondbrain-*' -ErrorAction SilentlyContinue)
if (-not $tasks) {
    Write-Host "No vesper-* (or legacy secondbrain-*) tasks registered. Nothing to do."
    return
}

foreach ($t in $tasks) {
    Write-Host "  removing: $($t.TaskName)"
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
}

Write-Host ""
Write-Host "Uninstalled $($tasks.Count) task(s)."
Write-Host "Logs preserved at .claude\data\logs\ -- delete manually if you want."
