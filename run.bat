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

:: Get python-version-specific library folder name (e.g. libs_nt_311)
for /f "tokens=*" %%i in ('^"^"!PYTHON_RUN!^" -c "import sys; print('libs_nt_' + str(sys.version_info.major) + str(sys.version_info.minor))"^"') do set "LIBS_FOLDER=%%i"
for /f "tokens=*" %%i in ('^"^"!PYTHON_RUN!^" -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"^"') do set "TARGET_PY_VER=%%i"

:: Determine libs directory based on whether we are running from USB (non-C: drive)
set "SCRIPT_DRIVE=%~d0"
if /i not "%SCRIPT_DRIVE%"=="C:" (
    set "LIBS_DIR=%LOCALAPPDATA%\2501-deepmemory\!LIBS_FOLDER!"
) else (
    set "LIBS_DIR=%~dp0!LIBS_FOLDER!"
)

:: Check if requirements are already installed
"!PYTHON_RUN!" -c "import sys; sys.path.insert(0, r'%LIBS_DIR%'); import bs4; import cryptography" >nul 2>&1
if !errorlevel! equ 0 goto :run

echo Installing requirements into '%LIBS_DIR%'...

:: Try portable Python pip first
"!PYTHON_RUN!" -m pip install --target "%LIBS_DIR%" -r "%~dp0requirements.txt" >nul 2>&1
if !errorlevel! equ 0 goto :run

:: Portable Python has no pip - fall back to system Python for install only
echo   (portable pip not available, using system Python for install)
python -m pip install --target "%LIBS_DIR%" --python-version !TARGET_PY_VER! --platform win_amd64 --only-binary=:all: -r "%~dp0requirements.txt" 2>nul
if !errorlevel! equ 0 goto :run

:: Last resort: try pip directly
pip install --target "%LIBS_DIR%" --python-version !TARGET_PY_VER! --platform win_amd64 --only-binary=:all: -r "%~dp0requirements.txt" 2>nul
if !errorlevel! equ 0 goto :run

echo Error: Failed to install requirements. Install Python with pip from python.org.
pause
exit /b 1

:run
echo Starting 2501...
"!PYTHON_RUN!" 2501.py %*
pause
