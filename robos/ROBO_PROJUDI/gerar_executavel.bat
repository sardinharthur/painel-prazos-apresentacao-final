@echo off
chcp 65001 >nul
echo ========================================================
echo   COMPILANDO ROBO PROJUDI (.EXE COM INTERFACE GRAFICA)
echo ========================================================
echo.
"C:\Users\Arthur\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m PyInstaller --noconfirm --onefile --noconsole --collect-all playwright --name "RoboProjudi" "robo_projudi_gui.py"
echo.
echo ========================================================
echo   CONCLUIDO! O executavel foi gerado em: dist\RoboProjudi.exe
echo ========================================================
pause
