@echo off
REM One-click EXE build: install dependencies and package with PyInstaller spec.
REM Note: keep this file ASCII-only and CRLF line endings for cmd.exe compatibility.
cd /d "%~dp0.."

echo ==========================================
echo   LoLMatchQuery - EXE Build
echo ==========================================

echo [1/2] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies, please check your network.
    pause
    exit /b 1
)

echo [2/2] Building EXE...
pyinstaller --noconfirm LoLMatchQuery.spec
if errorlevel 1 (
    echo Build failed, see the error message above.
    pause
    exit /b 1
)

echo.
echo Build complete! Output: dist\LoLMatchQuery.exe
pause
