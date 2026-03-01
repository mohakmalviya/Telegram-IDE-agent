import socket
import os
from pathlib import Path

def find_free_port():
    """Find a guaranteed empty port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port

def update_env(port):
    """Write the empty port to the .env file so the bot knows."""
    env_path = Path("D:/Telegram_agent/.env")
    lines = env_path.read_text('utf-8').splitlines()
    
    for i, line in enumerate(lines):
        if line.startswith("CDP_PORT="):
            lines[i] = f"CDP_PORT={port}"
            break
    
    env_path.write_text("\n".join(lines) + "\n", 'utf-8')
    print(f"Updated .env CDP_PORT={port}")

def update_bat(port):
    """Update the batch file so Antigravity launches with the same port."""
    bat_path = Path("D:/Telegram_agent/start_antigravity.bat")
    
    content = f"""@echo off
REM TEAM_001: Launch Antigravity on a dynamically assigned free port

setlocal

set "AG_PATH=%LOCALAPPDATA%\\Programs\\Antigravity\\Antigravity.exe"
if exist "%AG_PATH%" goto :launch

set "AG_PATH=%PROGRAMFILES%\\Antigravity\\Antigravity.exe"
if exist "%AG_PATH%" goto :launch

set "AG_PATH=%PROGRAMFILES(X86)%\\Antigravity\\Antigravity.exe"
if exist "%AG_PATH%" goto :launch

for /f "delims=" %%i in ('where Antigravity.exe 2^>nul') do (
    set "AG_PATH=%%i"
    goto :launch
)

echo.
echo ERROR: Could not find Antigravity.exe
pause
exit /b 1

:launch
echo Launching Antigravity with CDP enabled (port {port})...
start "" "%AG_PATH%" --remote-debugging-port={port}
"""
    bat_path.write_text(content, 'utf-8')
    print(f"Updated start_antigravity.bat for port {port}")

if __name__ == "__main__":
    port = find_free_port()
    print(f"Found free port: {port}")
    update_env(port)
    update_bat(port)
    print("Done! Setup script finished.")
