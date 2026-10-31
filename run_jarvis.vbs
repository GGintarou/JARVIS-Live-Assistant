Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\proko\.gemini\antigravity\scratch\jarvis_live"
WshShell.Run """C:\Users\proko\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\pythonw.exe"" jarvis_live.py", 0, False
