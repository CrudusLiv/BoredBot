' Hidden launcher for memory_index.py.
' wscript.exe is windowless, and Run with intWindowStyle=0 hides the
' py child too -- so the indexer runs every 10 min without a console flash.
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))))
indexScript = projectDir & "\.claude\scripts\memory\memory_index.py"
CreateObject("WScript.Shell").Run "py """ & indexScript & """", 0, False
