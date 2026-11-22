@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ROBO 1 - EPROC

REM O usuario sempre inicia por este arquivo.
if not exist ".venv\Scripts\python.exe" (
    echo ==========================================================
    echo        PRIMEIRA EXECUCAO - INSTALANDO O ROBO 1
    echo ==========================================================
    echo.
    call "_INSTALAR.bat"
    if errorlevel 1 (
        echo.
        echo A instalacao nao foi concluida.
        pause
        exit /b 1
    )
)

set "PWDEBUG="
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" launcher.py
