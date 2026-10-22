@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
  echo Python nu a fost gasit.
  echo Instalati Python 3.10 sau mai nou de la https://www.python.org/downloads/
  echo Bifati "Add python.exe to PATH", apoi rulati din nou porneste.bat.
  echo.
  pause
  exit /b 1
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

echo Pregatesc aplicatia...
"%PY%" -c "import server; raise SystemExit(server.pregateste())"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
echo Aplicatia porneste.
echo Deschideti in browser: http://127.0.0.1:8765
echo Pentru oprire apasati Ctrl+C.
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8765"
"%PY%" -u server.py
echo.
pause
