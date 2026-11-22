@echo off
chcp 65001 >nul
title Robo PROJUDI - Coleta de Prazos
cd /d "%~dp0"
if not exist "robos\projudi\projudi_config.json" (
    echo Primeira execucao: abrindo em modo de mapeamento (--mapear)...
    python "robos\projudi\robo_projudi_prazos.py" --mapear
) else (
    python "robos\projudi\robo_projudi_prazos.py"
)
pause
