Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = scriptDir

uvPy = WshShell.ExpandEnvironmentStrings("%APPDATA%\uv\python\cpython-3.15-windows-x86_64-none\pythonw.exe")
venvPy = scriptDir & "\.venv\Scripts\pythonw.exe"

If fso.FileExists(venvPy) Then
    WshShell.Run """" & venvPy & """ jarvis_live.py", 0, False
ElseIf fso.FileExists(uvPy) Then
    WshShell.Run """" & uvPy & """ jarvis_live.py", 0, False
Else
    WshShell.Run "pythonw.exe jarvis_live.py", 0, False
End If
