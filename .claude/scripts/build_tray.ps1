# Build VesperTray.exe
# Run from project root: .claude\scripts\build_tray.ps1

$ProjectDir = $PSScriptRoot | Split-Path -Parent | Split-Path -Parent
Set-Location $ProjectDir

py -m PyInstaller `
  --onefile `
  --windowed `
  --name VesperTray `
  --add-data ".env;." `
  --hidden-import "pystray._win32" `
  --hidden-import "customtkinter" `
  --hidden-import "PIL._tkinter_finder" `
  ".claude/scripts/tray_app.py"

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Build complete: dist\VesperTray.exe"
