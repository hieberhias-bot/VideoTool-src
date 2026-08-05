@echo off
setlocal
title DirectX 9.0c Runtime fuer Metin2
echo ================================================
echo    DirectX 9.0c Runtime (d3dx9) installieren
echo ================================================
echo Metin2 braucht die alten d3dx9-DLLs, die Windows 10/11
echo nicht mitbringt. Dieses Skript installiert sie nach.
echo.
set "DL=%TEMP%\directx_Jun2010_redist.exe"
set "EX=%TEMP%\dxredist"

echo [1/3] Lade DirectX-Redist (~95 MB) ...
curl -L -o "%DL%" "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe"
if not exist "%DL%" (
  echo.
  echo [X] Download fehlgeschlagen - Internetverbindung in der VM pruefen.
  echo     Alternativ "DirectX End-User Runtime Web Installer" manuell
  echo     von microsoft.com laden und ausfuehren.
  pause
  exit /b 1
)

echo [2/3] Entpacke ...
if not exist "%EX%" mkdir "%EX%"
"%DL%" /Q /C /T:"%EX%"

echo [3/3] Installiere (still) ...
"%EX%\DXSETUP.exe" /silent

echo.
echo ================================================
echo    Fertig. Metin2 jetzt erneut starten.
echo ================================================
pause
