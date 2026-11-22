@echo off
chcp 65001 > nul
title Robo 2 - eProtocolo

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo O ambiente virtual do Robo 2 ainda nao existe.
    echo Execute primeiro o arquivo INSTALAR.bat.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py

echo.
pause