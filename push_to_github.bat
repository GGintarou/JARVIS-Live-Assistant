@echo off
chcp 65001 >nul
title Push JARVIS Live Assistant to GitHub
cd /d "%~dp0"
cls
echo ======================================================================
echo    J.A.R.V.I.S. LIVE ASSISTANT - GITHUB SYNC
echo    Repository: https://github.com/GGintarou/JARVIS-Live-Assistant
echo ======================================================================
echo.
echo Pushing branch 'main' to GitHub...
echo.

git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo ======================================================================
    echo   [SUCCESS] All files, documentation and HUD assets published!
    echo   Repository URL: https://github.com/GGintarou/JARVIS-Live-Assistant
    echo ======================================================================
) else (
    echo.
    echo ======================================================================
    echo   [ERROR] Push failed. Please check your GitHub authorization.
    echo ======================================================================
)

echo.
pause
