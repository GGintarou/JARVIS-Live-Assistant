Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\proko\.gemini\antigravity\scratch\jarvis_live"
WshShell.Run """C:\Users\proko\.gemini\antigravity\scratch\jarvis_live\.venv\Scripts\pythonw.exe"" jarvis_live.py", 0, False
