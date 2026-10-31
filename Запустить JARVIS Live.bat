@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 1. Проверяем наличие Python в локальном виртуальном окружении
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" jarvis_live.py
    exit /b
)

REM 2. Проверяем Python в окружении uv
if exist "%APPDATA%\uv\python\cpython-3.15-windows-x86_64-none\pythonw.exe" (
    start "" "%APPDATA%\uv\python\cpython-3.15-windows-x86_64-none\pythonw.exe" jarvis_live.py
    exit /b
)

REM 3. Стандартный запуск через pythonw в системе
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw jarvis_live.py
    exit /b
)

REM 4. Запасной запуск через python с отображением консоли
python jarvis_live.py
pause
