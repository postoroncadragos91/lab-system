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

"%PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
  echo Python nu poate deschide o fereastra.
  echo Reinstalati Python de la https://www.python.org/downloads/
  echo si lasati bifat "tcl/tk and IDLE".
  echo.
  pause
  exit /b 1
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

echo Pregatesc aplicatia...
"%PY%" -c "import cautare; raise SystemExit(cautare.pregateste())"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

set "PYW="
where pythonw >nul 2>&1 && set "PYW=pythonw"
if not defined PYW where pyw >nul 2>&1 && set "PYW=pyw"

echo Se deschide fereastra Cautare pacient.
if defined PYW (
  start "" /D "%~dp0" "%PYW%" "%~dp0cautare.py"
  exit /b 0
)

"%PY%" "%~dp0cautare.py"
if errorlevel 1 pause
