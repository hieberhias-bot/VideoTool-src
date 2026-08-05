@echo off
setlocal enabledelayedexpansion
title Automation Command Center - Einrichtung
echo ============================================
echo    Automation Command Center - Einrichtung
echo ============================================
echo.

REM --- Programm auf den Desktop kopieren ---
set "ZIEL=%USERPROFILE%\Desktop\VideoTool-src"
echo Kopiere Programm nach:
echo    %ZIEL%
robocopy "%~dp0." "%ZIEL%" /E /XD .git __pycache__ .vscode /XF *.bak >nul
echo    ...erledigt.
echo.

REM --- Python suchen ---
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
  echo [!] Kein Python gefunden - versuche Installation ueber winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  where py >nul 2>&1 && set "PY=py"
  if not defined PY ( where python >nul 2>&1 && set "PY=python" )
)

if not defined PY (
  echo.
  echo [X] Python konnte nicht gefunden/installiert werden.
  echo     Bitte Python 3 von python.org installieren ^(Haken "Add to PATH"^)
  echo     und dieses Skript danach erneut ausfuehren.
  echo.
  pause
  exit /b 1
)

echo Verwende Python: %PY%
echo.
echo Installiere Pakete: pynput, pyserial, pyautogui ...
%PY% -m pip install --upgrade pip
%PY% -m pip install pynput pyserial pyautogui
echo.
echo ============================================
echo    Fertig!
echo    Starten:  %ZIEL%\CommandCenter.bat
echo             (oder: %PY% "%ZIEL%\command_center.py")
echo ============================================
echo.
pause
