@echo off
title JARVIS GitHub Publisher
cls
echo ========================================================
echo   J.A.R.V.I.S. LIVE ASSISTANT - GITHUB SYNC
echo   Target: https://github.com/GGintarou/JARVIS-Live-Assistant
echo ========================================================
echo.

cd /d "%~dp0"

echo Current directory:
cd
echo.
echo Checking Git status:
git status --short
echo.
echo ========================================================
echo Pushing 'main' branch to GitHub...
echo (If Git Credential Manager prompts you, click 'Sign in with browser')
echo ========================================================
echo.

git push -u origin main

echo.
if %errorlevel% equ 0 (
    echo ========================================================
    echo [SUCCESS] JARVIS successfully published to GitHub!
    echo URL: https://github.com/GGintarou/JARVIS-Live-Assistant
    echo ========================================================
) else (
    echo ========================================================
    echo [ERROR] Push failed with error code %errorlevel%.
    echo ========================================================
)
echo.
pause
