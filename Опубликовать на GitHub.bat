@echo off
chcp 65001 >nul
title Публикация JARVIS Live Assistant на GitHub
cd /d "%~dp0"
cls
echo ======================================================================
echo    J.A.R.V.I.S. LIVE ASSISTANT — СИНХРОНИЗАЦИЯ С GITHUB
echo    Репозиторий: https://github.com/GGintarou/JARVIS-Live-Assistant
echo ======================================================================
echo.
echo Отправляем ветку main на GitHub...
echo (Если откроется окно браузера или Git Credential Manager,
echo  нажмите «Sign in with your browser» для подтверждения авторизации)
echo.

git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo ======================================================================
    echo   [УСПЕШНО] Все файлы, документация и картинки загружены на GitHub!
    echo   Ссылка на репозиторий:
    echo   https://github.com/GGintarou/JARVIS-Live-Assistant
    echo ======================================================================
) else (
    echo.
    echo ======================================================================
    echo   [ОШИБКА] Не удалось выполнить отправку.
    echo   Проверьте интернет-соединение или авторизацию GitHub.
    echo ======================================================================
)

echo.
pause
