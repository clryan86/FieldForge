@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B -m fieldforge_gps --workspace
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -B -m fieldforge_gps --workspace
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python -B -m fieldforge_gps --workspace
  goto finished
)
echo Python 3.10 or later with Tk is needed for this source add-on.
echo See docs\GPS_WORKSPACE.md. This does not modify FieldForge.exe.
pause
exit /b 1
:finished
if errorlevel 1 pause
endlocal
