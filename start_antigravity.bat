@echo off
REM TEAM_002: Launch Antigravity with CDP on an auto-selected free port
REM (ported from LazyGravity's start_antigravity_win.bat)

setlocal enabledelayedexpansion

REM === Find Antigravity.exe ===
set "AG_PATH=%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe"
if exist "%AG_PATH%" goto :found

set "AG_PATH=%PROGRAMFILES%\Antigravity\Antigravity.exe"
if exist "%AG_PATH%" goto :found

set "AG_PATH=%PROGRAMFILES(X86)%\Antigravity\Antigravity.exe"
if exist "%AG_PATH%" goto :found

for /f "delims=" %%i in ('where Antigravity.exe 2^>nul') do (
    set "AG_PATH=%%i"
    goto :found
)

echo.
echo ERROR: Could not find Antigravity.exe
echo Install Antigravity from https://antigravity.dev
pause
exit /b 1

:found

REM === Auto-select free CDP port (like LazyGravity) ===
set PORTS=9222 9223 9333 9444 9555 9666
set CDP_PORT=

for %%p in (%PORTS%) do (
    if not defined CDP_PORT (
        netstat -an | findstr "LISTENING" | findstr ":%%p " >nul 2>&1
        if errorlevel 1 (
            set CDP_PORT=%%p
        )
    )
)

if not defined CDP_PORT (
    echo ERROR: All CDP ports are in use. Close other Chromium-based apps.
    pause
    exit /b 1
)

echo.
echo  Launching Antigravity with CDP on port %CDP_PORT%...
echo.

REM === Update .env with the selected port ===
set "ENV_FILE=%~dp0.env"
if exist "%ENV_FILE%" (
    powershell -Command "(Get-Content '%ENV_FILE%') -replace '^CDP_PORT=.*', 'CDP_PORT=%CDP_PORT%' | Set-Content '%ENV_FILE%'"
    echo  Updated .env: CDP_PORT=%CDP_PORT%
)

start "" "%AG_PATH%" --remote-debugging-port=%CDP_PORT%
echo  Antigravity started. Wait a few seconds, then start the bot.
echo.
pause
