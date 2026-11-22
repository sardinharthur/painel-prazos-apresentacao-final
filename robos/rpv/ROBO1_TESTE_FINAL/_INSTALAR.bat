@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo   INSTALACAO - ROBO EPROC RPV
echo ==========================================
echo.

set "PYEXE="

REM 1) Tenta o launcher oficial do Python para Windows
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYEXE=py -3"
)

REM 2) Tenta python.exe apenas se for um Python real, e nao o alias da Microsoft Store
if not defined PYEXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 set "PYEXE=python"
    )
)

REM 3) Procura instalacoes comuns do Python no perfil do usuario
if not defined PYEXE (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do (
        if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)

REM 4) Procura instalacoes comuns em Program Files
if not defined PYEXE (
    for /d %%D in ("C:\Program Files\Python*") do (
        if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)

if not defined PYEXE (
    echo ERRO: Nao encontrei uma instalacao real do Python.
    echo.
    echo O Windows esta encontrando apenas o atalho da Microsoft Store.
    echo.
    echo Tente no Prompt de Comando:
    echo     py --version
    echo.
    echo Se isso tambem falhar, reinstale o Python pelo instalador oficial
    echo e marque a opcao "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo Python encontrado:
%PYEXE% --version
echo.

echo [1/4] Criando ambiente virtual...
%PYEXE% -m venv .venv
if errorlevel 1 goto erro

echo [2/4] Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto erro

echo [3/4] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erro

echo [4/4] Instalando Chromium do Playwright...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto erro

echo.
echo ==========================================
echo   INSTALACAO CONCLUIDA COM SUCESSO
echo ==========================================
pause
exit /b 0

:erro
echo.
echo ==========================================
echo   ERRO DURANTE A INSTALACAO
echo ==========================================
echo Envie uma foto das ultimas linhas desta janela.
pause
exit /b 1
