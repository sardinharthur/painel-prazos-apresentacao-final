@echo off
cd /d "%~dp0"

set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if exist "%PY%" goto run

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
    goto run
)

set "PY=python"

:run
%PY% -m pip install -r requirements.txt
pause
