"""Scan Windows for installed applications — Start Menu shortcuts, App Paths
registry, and the Programs-and-Features Uninstall registry.

Three sources, deduplicated by resolved target path:
  1. Start Menu .lnk files (user + all-users), resolved via one batched
     PowerShell COM call (NOT one process per shortcut — a Start Menu with
     ~100+ shortcuts made per-file subprocess spawns take 60-120s+; batching
     resolves them all in a single ~1s PowerShell invocation)
  2. HKLM/HKCU App Paths registry keys
  3. HKLM/HKCU Uninstall registry keys (what Control Panel > Programs and
     Features reads). Games installed via Steam/Epic/Riot/etc. rarely get a
     Start Menu shortcut or an App Paths entry, but almost always register
     here with an InstallLocation or DisplayIcon pointing at the real exe —
     on whichever drive they were installed to, since installer-registered
     paths are absolute and drive-agnostic (unlike scanning a fixed drive).

Returns AppEntry list; callers approve entries via voice.approved_apps before
launch_app.py will use them.
"""
from __future__ import annotations

import json
import os
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


# Executable name fragments that mean "not the game/app itself" — installers,
# redistributables, anti-cheat services, crash reporters. Skipped when picking
# a candidate exe out of an Uninstall entry's InstallLocation folder.
_EXE_BLACKLIST_SUBSTR = (
    "unins", "setup", "redist", "vcredist", "vc_redist", "dxsetup", "directx",
    "crashpad", "crashreporter", "crashhandler", "easyanticheat", "battleye",
    "dotnet", "prereq", "ueprereq", "updater", "helper", "cef_",
)


def _pick_exe(display_name: str, candidates: list[Path]) -> Path | None:
    """Pick the most likely "main" exe from a folder's worth of candidates:
    prefer one whose filename resembles the app's display name, tie-broken by
    file size (a game's main exe is typically the largest one present)."""
    if not candidates:
        return None
    norm_name = "".join(ch for ch in display_name.lower() if ch.isalnum())
    scored = []
    for c in candidates:
        stem = "".join(ch for ch in c.stem.lower() if ch.isalnum())
        name_match = bool(stem) and bool(norm_name) and (stem in norm_name or norm_name in stem)
        try:
            size = c.stat().st_size
        except OSError:
            size = 0
        scored.append((name_match, size, c))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def _find_exe_in(install_dir: Path, display_name: str, max_depth: int = 3, max_scanned: int = 500) -> Path | None:
    """Bounded-depth search for a candidate exe under an Uninstall entry's
    InstallLocation (used only when DisplayIcon didn't already give us one).
    Depth- and file-count-capped so one slow/huge folder can't stall the scan."""
    candidates: list[Path] = []
    scanned = 0
    base_depth = len(install_dir.parts)
    try:
        for root, dirs, files in os.walk(install_dir):
            if len(Path(root).parts) - base_depth >= max_depth:
                dirs[:] = []
            for f in files:
                if scanned >= max_scanned:
                    break
                scanned += 1
                low = f.lower()
                if not low.endswith(".exe") or any(b in low for b in _EXE_BLACKLIST_SUBSTR):
                    continue
                candidates.append(Path(root) / f)
            if scanned >= max_scanned:
                break
    except OSError:
        return None
    return _pick_exe(display_name, candidates)


def _scan_uninstall() -> list[AppEntry]:
    entries: list[AppEntry] = []
    seen_targets: set[str] = set()
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
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
                            def _val(value_name: str):
                                try:
                                    v, _ = winreg.QueryValueEx(app_key, value_name)
                                    return v
                                except OSError:
                                    return None

                            display_name = _val("DisplayName")
                            if not display_name or _val("SystemComponent") == 1 or _val("ParentKeyName"):
                                continue  # no name, or a hidden update/sub-component, not a real app

                            target: Path | None = None
                            icon = _val("DisplayIcon")
                            if icon:
                                icon_path = str(icon).split(",")[0].strip().strip('"')
                                if icon_path.lower().endswith(".exe") and Path(icon_path).is_file():
                                    target = Path(icon_path)
                            if target is None:
                                loc = _val("InstallLocation")
                                if loc and Path(loc).is_dir():
                                    target = _find_exe_in(Path(loc), str(display_name))
                            if target is None:
                                continue

                            key_str = str(target).lower()
                            if key_str in seen_targets:
                                continue
                            seen_targets.add(key_str)
                            entries.append(AppEntry(name=str(display_name), path=str(target), source="uninstall"))
                    except OSError:
                        continue
        except OSError:
            continue
    return entries


def scan_all() -> list[AppEntry]:
    """Scan Start Menu + App Paths registry + Uninstall registry, merge, dedupe
    by resolved path (case-insensitive)."""
    from voice import approved_apps

    approved = approved_apps.get_approved()  # alias -> path
    approved_paths = {p.lower() for p in approved.values()}

    seen: dict[str, AppEntry] = {}
    for entry in _scan_start_menu() + _scan_registry() + _scan_uninstall():
        key = entry.path.lower()
        if key not in seen:
            if key in approved_paths:
                entry.approved = True
                entry.voice_alias = next(
                    (alias for alias, p in approved.items() if p.lower() == key), ""
                )
            seen[key] = entry
    return sorted(seen.values(), key=lambda e: e.name.lower())
