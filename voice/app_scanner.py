"""Scan Windows for installed applications — Start Menu shortcuts + App Paths registry.

Two sources, deduplicated by resolved target path:
  1. Start Menu .lnk files (user + all-users), resolved via one batched
     PowerShell COM call (NOT one process per shortcut — a Start Menu with
     ~100+ shortcuts made per-file subprocess spawns take 60-120s+; batching
     resolves them all in a single ~1s PowerShell invocation)
  2. HKLM/HKCU App Paths registry keys

Returns AppEntry list; callers approve entries via voice.approved_apps before
launch_app.py will use them.
"""
from __future__ import annotations

import json
import subprocess
import winreg
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppEntry:
    name: str
    path: str
    source: str  # "start_menu" | "registry"
    approved: bool = False
    voice_alias: str = field(default="")


_RESOLVE_LNKS_PS = """
$sh = New-Object -ComObject WScript.Shell
$dirs = @($args)
$results = foreach ($d in $dirs) {
    if (Test-Path $d) {
        Get-ChildItem -Path $d -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $target = $sh.CreateShortcut($_.FullName).TargetPath
                if ($target) { [PSCustomObject]@{ name = $_.BaseName; target = $target } }
            } catch {}
        }
    }
}
$results | ConvertTo-Json -Compress
"""


def _scan_start_menu() -> list[AppEntry]:
    import os
    dirs = [
        str(Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"),
        str(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"),
    ]
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _RESOLVE_LNKS_PS, *dirs],
            capture_output=True, text=True, timeout=20,
        )
        raw = json.loads(r.stdout.strip() or "[]")
    except Exception:
        return []
    if isinstance(raw, dict):  # ConvertTo-Json emits an object, not an array, for a single result
        raw = [raw]

    entries: list[AppEntry] = []
    seen_targets: set[str] = set()
    for item in raw:
        target = (item.get("target") or "").strip()
        name = item.get("name") or ""
        if not target or target.lower() in seen_targets:
            continue
        seen_targets.add(target.lower())
        entries.append(AppEntry(name=name, path=target, source="start_menu"))
    return entries


def _scan_registry() -> list[AppEntry]:
    entries: list[AppEntry] = []
    seen_targets: set[str] = set()
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for hive, subkey in roots:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, name) as app_key:
                            path, _ = winreg.QueryValueEx(app_key, "")
                    except OSError:
                        continue
                    if not path or path.lower() in seen_targets:
                        continue
                    seen_targets.add(path.lower())
                    entries.append(AppEntry(name=Path(name).stem, path=path, source="registry"))
        except OSError:
            continue
    return entries


def scan_all() -> list[AppEntry]:
    """Scan Start Menu + registry, merge, dedupe by resolved path (case-insensitive)."""
    from voice import approved_apps

    approved = approved_apps.get_approved()  # alias -> path
    approved_paths = {p.lower() for p in approved.values()}

    seen: dict[str, AppEntry] = {}
    for entry in _scan_start_menu() + _scan_registry():
        key = entry.path.lower()
        if key not in seen:
            if key in approved_paths:
                entry.approved = True
                entry.voice_alias = next(
                    (alias for alias, p in approved.items() if p.lower() == key), ""
                )
            seen[key] = entry
    return sorted(seen.values(), key=lambda e: e.name.lower())
