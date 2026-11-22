@echo off
chcp 65001 > nul
title Instalacao - Robo 2 eProtocolo

echo ==========================================
echo   CONFIGURANDO AMBIENTE DO ROBO 2
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual exclusivo...
    py -3 -m venv .venv

    if errorlevel 1 (
        echo.
        echo ERRO: Nao foi possivel criar o ambiente virtual.
        echo Verifique se o comando "py" funciona.
        pause
        exit /b 1
    )
)

echo.
echo Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo.
echo Instalando dependencias SOMENTE no Robo 2...
".venv\Scripts\python.exe" -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERRO ao instalar as dependencias.
    pause
    exit /b 1
)

echo.
echo Instalando Chromium do Playwright...
".venv\Scripts\python.exe" -m playwright install chromium

if errorlevel 1 (
    echo.
    echo ERRO ao instalar o Chromium.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   ROBO 2 CONFIGURADO COM SUCESSO
echo ==========================================
echo.
echo Ambiente utilizado:
echo %CD%\.venv
echo.
pause