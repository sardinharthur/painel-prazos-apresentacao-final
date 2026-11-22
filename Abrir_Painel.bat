@echo off
chcp 65001 >nul
title Painel de Prazos - Avaliacao FESPPR
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 servidor_avaliacao.py
    goto :fim
)
where python >nul 2>nul
if %errorlevel%==0 (
    python servidor_avaliacao.py
    goto :fim
)
echo Instale o Python 3.11 ou mais recente e abra este arquivo novamente.
:fim
pause
