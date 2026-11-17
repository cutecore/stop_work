@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Creating environment...
    py -3 -m venv .venv
    if errorlevel 1 goto fail
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 goto fail
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0

:fail
echo Setup failed. Check Python 3 and the network, then run this file again.
pause
exit /b 1
