@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_RoomWise.ps1"
set "roomwiseExitCode=%errorlevel%"
if not "%roomwiseExitCode%"=="0" (
    echo.
    echo RoomWise could not start. Read the message above.
    pause
)
endlocal & exit /b %roomwiseExitCode%
