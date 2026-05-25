@echo off
setlocal enabledelayedexpansion

echo --- 2501 DeepMemory Launcher (Windows Portable) ---

:: Determine Python for running the app (portable first, then system)
set PYTHON_RUN=python
if exist "bin\python\python.exe" (
    set PYTHON_RUN=bin\python\python.exe
    echo Using portable Python from USB.
) else (
    python --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo Error: Python is not installed and no portable version found.
        pause
        exit /b 1
    )
)

:: Check if requirements are already installed
"!PYTHON_RUN!" -c "import sys; sys.path.insert(0, './libs_nt'); import bs4; import cryptography" >nul 2>&1
if !errorlevel! equ 0 goto :run

echo Installing requirements into local 'libs_nt' folder...

:: Try portable Python pip first
"!PYTHON_RUN!" -m pip install --target ./libs_nt -r requirements.txt >nul 2>&1
if !errorlevel! equ 0 goto :run

:: Portable Python has no pip - fall back to system Python for install only
echo   (portable pip not available, using system Python for install)
python -m pip install --target ./libs_nt -r requirements.txt 2>nul
if !errorlevel! equ 0 goto :run

:: Last resort: try pip directly
pip install --target ./libs_nt -r requirements.txt 2>nul
if !errorlevel! equ 0 goto :run

echo Error: Failed to install requirements. Install Python with pip from python.org.
pause
exit /b 1

:run
echo Starting 2501...
"!PYTHON_RUN!" 2501.py %*
pause
