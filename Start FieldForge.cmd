@echo off
setlocal
cd /d "%~dp0"
if not exist "fieldforge\ui\desktop.py" (
    echo Extract the entire FieldForge folder first, then open this launcher there.
    pause
    exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
    echo Python's py launcher was not found. Install Python 3.10 or newer with Tkinter.
    echo This launcher does not install software or change system settings.
    pause
    exit /b 1
)
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or newer is required.
    pause
    exit /b 1
)
if not defined FIELDFORGE_DB set "FIELDFORGE_DB=%USERPROFILE%\.fieldforge\playground.db"
echo Opening FieldForge with database: "%FIELDFORGE_DB%"
echo This is a development build. Close FieldForge normally to save private notes.
py -3 -m fieldforge.ui.desktop
if errorlevel 1 (
    echo.
    echo FieldForge did not exit normally. Keep this window open to read the error above.
    pause
    exit /b 1
)
endlocal
