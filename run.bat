@echo off
setlocal enabledelayedexpansion

echo --- 2501 DeepMemory Launcher (Windows Portable) ---

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Check if requirements are installed (heuristic: check if bs4 and cryptography are available)
python -c "import sys; sys.path.insert(0, './libs'); import bs4; import cryptography" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing requirements into local 'libs' folder...
    if exist "libs" rmdir /s /q libs
    mkdir libs
    python -m pip install --target ./libs -r requirements.txt
    if %errorlevel% neq 0 (
        echo Error: Failed to install requirements.
        pause
        exit /b 1
    )
)

:: Run the application
echo Starting 2501...
python 2501.py %*
pause
