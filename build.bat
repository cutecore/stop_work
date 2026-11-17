@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating environment...
    py -3 -m venv .venv
    if errorlevel 1 goto fail
)
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt" pyinstaller
if errorlevel 1 goto fail
if not exist "%~dp0stopwork.ico" (
    ".venv\Scripts\python.exe" "%~dp0make_icon.py"
    if errorlevel 1 goto fail
)
echo Building dist\StopWork.exe ...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile --name StopWork --icon "%~dp0stopwork.ico" "%~dp0main.py"
if errorlevel 1 goto fail
echo Built dist\StopWork.exe
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
