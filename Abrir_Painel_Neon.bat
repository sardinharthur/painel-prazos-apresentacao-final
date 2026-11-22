@echo off
chcp 65001 >nul
title Painel de Prazos - Procuradoria de Saude (PRS)
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" servidor_painel.py
    goto :fim
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 servidor_painel.py
    goto :fim
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" servidor_painel.py
        goto :fim
    )
)

python servidor_painel.py

:fim
pause
