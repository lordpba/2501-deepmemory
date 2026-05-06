#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "--- 2501 DeepMemory Launcher (Portable) ---"

# Determine Local Cache Directory for Linux
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/2501-deepmemory"
mkdir -p "$CACHE_DIR"

VENV_DIR="$CACHE_DIR/venv"
LIBS_DIR="$CACHE_DIR/libs_posix"

# 1. Try to use/create virtual environment in Local Cache
if [ ! -d "$VENV_DIR" ] && [ ! -d "$LIBS_DIR" ]; then
    echo "First run on this machine. Preparing local environment..."
    python3 -m venv "$VENV_DIR" 2>/dev/null
fi

# 2. Setup the execution path
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python3"
    mkdir -p "$LIBS_DIR"
    export PYTHONPATH="$PYTHONPATH:$LIBS_DIR"
fi

# 3. Check dependencies
if ! $PYTHON_CMD -c "import httpx" &> /dev/null; then
    echo "Installing requirements for this machine..."
    if [ -d "$VENV_DIR" ]; then
        $PYTHON_CMD -m pip install -r requirements.txt
    else
        $PYTHON_CMD -m pip install -t "$LIBS_DIR" -r requirements.txt
    fi
fi

# 4. Launch 2501
echo "Starting 2501..."
$PYTHON_CMD 2501.py "$@"
