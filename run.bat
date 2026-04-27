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

:: Check if requirements are installed in local libs
python -c "import sys; sys.path.insert(0, './libs'); import httpx" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing requirements into local 'libs' folder...
    if not exist "libs" mkdir libs
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
