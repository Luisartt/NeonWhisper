@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo NeonWhisper no esta instalado todavia. Ejecuta Instalar.bat primero.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0NeonWhisper.pyw"
