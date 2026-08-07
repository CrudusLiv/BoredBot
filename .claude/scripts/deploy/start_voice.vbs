Set fso = CreateObject("Scripting.FileSystemObject")
deployDir = fso.GetParentFolderName(WScript.ScriptFullName)
launchScript = deployDir & "\start_voice.ps1"
CreateObject("WScript.Shell").Run "pwsh -ExecutionPolicy Bypass -File """ & launchScript & """", 0, False
