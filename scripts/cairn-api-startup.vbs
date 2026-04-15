' Cairn API auto-start — runs uvicorn silently on Windows login
' Place shortcut in shell:startup or register as scheduled task

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\claw"
WshShell.Run "D:\claw\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8765", 0, False
