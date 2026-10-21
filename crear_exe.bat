@echo off
cd /d "%~dp0"
echo ============================================
echo   Creando escaner_bluetooth.exe
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado o no esta en el PATH.
    echo Descargalo de https://www.python.org/downloads/
    echo y marca la casilla "Add python.exe to PATH" al instalar.
    pause
    exit /b 1
)

if not exist escaner_bluetooth.py (
    echo ERROR: No encuentro escaner_bluetooth.py en esta carpeta.
    pause
    exit /b 1
)

echo [1/2] Instalando dependencias...
python -m pip install --upgrade bleak pyinstaller
if errorlevel 1 (
    echo ERROR instalando dependencias.
    pause
    exit /b 1
)

echo.
echo [2/2] Generando el .exe (puede tardar un par de minutos)...
python -m PyInstaller --onefile --windowed --collect-all bleak escaner_bluetooth.py
if errorlevel 1 (
    echo ERROR generando el .exe.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Listo. Tu programa esta en: dist\escaner_bluetooth.exe
echo ============================================
pause
