@echo off
REM ======================================================================
REM  Bookbench als Windows-Programm bauen (PyInstaller), wie beim Keller-Tool
REM
REM  build_windows.bat            -> Ordner  packaging\dist\Bookbench\  (Bookbench.exe)
REM  build_windows.bat installer  -> dazu   packaging\dist\Bookbench_Setup_<Version>.exe
REM                                  (braucht Inno Setup 6, kostenlos:
REM                                   https://jrsoftware.org/isdl.php)
REM
REM  Danach für ein Release: python tools\make_release.py --summen packaging\dist\Bookbench_Setup_<Version>.exe
REM  schreibt SHA256SUMS; beide Dateien an die Veröffentlichung auf GitHub hängen.
REM ======================================================================

setlocal
cd /d "%~dp0"

set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
    python --version >nul 2>&1 && set PY=python
)
if not defined PY (
    echo Python wurde nicht gefunden. Bitte Python 3 installieren und beim
    echo Setup "Add python.exe to PATH" ankreuzen.
    pause
    exit /b 1
)
echo Verwende:
%PY% --version

echo.
echo Installiere/aktualisiere PyInstaller und die Zusatzpakete ...
%PY% -m pip install --upgrade pyinstaller -r ..\requirements.txt
if errorlevel 1 (
    echo.
    echo PyInstaller konnte nicht installiert werden - Meldungen oben pruefen.
    pause
    exit /b 1
)

REM Inno Setup vorab suchen (ohne Klammerbloecke: "%ProgramFiles(x86)%" enthaelt eine Klammer)
set ISCC=
if /i not "%1"=="installer" goto iscc_fertig
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC goto iscc_fertig
echo Inno Setup 6 wurde nicht gefunden. Bitte installieren:
echo   https://jrsoftware.org/isdl.php
pause
exit /b 1
:iscc_fertig

echo.
%PY% -m PyInstaller --noconfirm --clean bookbench.spec
if errorlevel 1 (
    echo.
    echo Build fehlgeschlagen - Meldungen oben pruefen.
    pause
    exit /b 1
)

if /i not "%1"=="installer" goto kein_installer
for /f "delims=" %%v in ('%PY% version.py') do set VERSION=%%v
echo.
echo Baue Installer (Version %VERSION%) ...
%ISCC% /DAppVersion=%VERSION% bookbench.iss
if errorlevel 1 goto fehler_installer
echo.
echo Fertig: packaging\dist\Bookbench_Setup_%VERSION%.exe
pause
exit /b 0
:fehler_installer
echo.
echo Installer-Build fehlgeschlagen - Meldungen oben pruefen.
pause
exit /b 1
:kein_installer

echo.
echo Fertig: packaging\dist\Bookbench\Bookbench.exe
pause
