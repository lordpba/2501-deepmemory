@echo off
setlocal enabledelayedexpansion

echo --- 2501 DeepMemory Launcher (Windows Portable) ---

:: Check for Portable Python on USB
if exist "bin\python\python.exe" (
    set PYTHON_CMD=bin\python\python.exe
    echo Using portable Python from USB.
) else (
    set PYTHON_CMD=python
    :: Check if system Python is installed
    !PYTHON_CMD! --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo Error: Python is not installed and no portable version found.
        pause
        exit /b 1
    )
)

:: Check if requirements are installed (heuristic: check if bs4 and cryptography are available)
!PYTHON_CMD! -c "import sys; sys.path.insert(0, './libs_nt'); import bs4; import cryptography" >nul 2>&1
if !errorlevel! neq 0 (
    echo Installing requirements into local 'libs_nt' folder...
    !PYTHON_CMD! -m pip install --target ./libs_nt -r requirements.txt
    if !errorlevel! neq 0 (
        echo Error: Failed to install requirements.
        pause
        exit /b 1
    )
)

:: Run the application
echo Starting 2501...
!PYTHON_CMD! 2501.py %*
pause
