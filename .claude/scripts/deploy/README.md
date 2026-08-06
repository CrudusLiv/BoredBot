# Deployment (Phase 9)

Local-only Windows install. One installer, four scheduled tasks, no services.

## Install

Open PowerShell **as Administrator** (Register-ScheduledTask requires it, even for user-scoped tasks):

```powershell
pwsh -ExecutionPolicy Bypass -File .claude\scripts\deploy\install_tasks.ps1
```

Idempotent — re-running replaces any existing `vesper-*` task (and removes
legacy `secondbrain-*` names from older installs).

| Task | Trigger | Action |
| --- | --- | --- |
| `vesper-heartbeat` | Daily 09:00 KL, repeats every 30 min for 13 hours | `py heartbeat.py` |
| `vesper-reflect` | Daily 08:00 KL | `py memory_reflect.py` |
| `vesper-index` | Every 10 min, all day | `py memory/memory_index.py` |
| `vesper-voice` | At logon, restart on failure | `start_voice.ps1` (`py -m voice --voice`) |

## Inspect

```powershell
Get-ScheduledTask -TaskName 'vesper-*' |
    Format-Table TaskName, State, LastRunTime, NextRunTime
Get-ScheduledTaskInfo -TaskName 'vesper-heartbeat'
```

Tail logs:

```powershell
Get-Content .claude\data\logs\voice-*.log -Wait -Tail 20
```

## Uninstall

```powershell
pwsh -ExecutionPolicy Bypass -File .claude\scripts\deploy\uninstall_tasks.ps1
```

Removes all four tasks. Logs and vault data are preserved — delete manually if wanted.

## Notes

- `heartbeat.py` self-gates via `in_active_hours()`; the 13-hour repetition window is belt-and-suspenders.
- The voice wrapper (`start_voice.ps1`) has two restart layers: inner `while ($true)` loop with exponential backoff on fast-fails, plus Task Scheduler `RestartCount=999` if PowerShell itself dies.
- Tasks run as the current user with `RunLevel Limited` so Windows Toast notifications can surface on the desktop.
- Docker was evaluated and dropped: the voice app needs direct mic/speaker access, a system tray icon, and Windows Toast notifications, none of which work well in a container. Task Scheduler is the deployment path.
