@echo off
REM Builds the Windows programs into dist\release\
REM   TreeRot.exe      - opens the window
REM   TreeRot-cli.exe  - for the command prompt, scripts and Task Scheduler
setlocal
cd /d "%~dp0"

if defined PYTHON (
  set "PY=%PYTHON%"
) else (
  where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")
)

if not exist .venv-build\Scripts\python.exe (
  echo === Creating the build environment .venv-build ===
  %PY% -m venv .venv-build || goto :error
)
set "VPY=.venv-build\Scripts\python.exe"

echo === Installing the build tool ===
"%VPY%" -m pip install --upgrade pip || goto :error
"%VPY%" -m pip install -r requirements-build.txt || goto :error

set "ICON="
if exist app.ico set "ICON=--icon app.ico"

echo === Building TreeRot.exe (window) ===
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed %ICON% ^
  --name TreeRot treerot.py || goto :error

echo === Building TreeRot-cli.exe (command line) ===
"%VPY%" -m PyInstaller --noconfirm --onefile --console %ICON% ^
  --name TreeRot-cli treerot.py || goto :error

if exist dist\release rmdir /s /q dist\release
mkdir dist\release || goto :error
copy /y dist\TreeRot.exe dist\release\ >nul || goto :error
copy /y dist\TreeRot-cli.exe dist\release\ >nul || goto :error

echo.
echo Done:
echo   dist\release\TreeRot.exe
echo   dist\release\TreeRot-cli.exe
goto :eof

:error
echo.
echo BUILD FAILED
exit /b 1
