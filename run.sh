#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "--- 2501 DeepMemory Launcher (Portable) ---"

# 1. Try to use/create virtual environment
if [ ! -f "venv/bin/activate" ] && [ ! -d "libs" ]; then
    echo "First run detected. Preparing environment..."
    python3 -m venv --copies venv 2>/dev/null
fi

# 2. Setup the execution path
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python3"
    mkdir -p libs
    export PYTHONPATH="$PYTHONPATH:$(pwd)/libs"
fi

# 3. Check dependencies (using bs4 as a marker for recent updates)
if ! $PYTHON_CMD -c "import bs4" &> /dev/null; then
    echo "Installing/Updating requirements..."
    if [ -f "venv/bin/activate" ]; then
        $PYTHON_CMD -m pip install -r requirements.txt
    else
        $PYTHON_CMD -m pip install -t libs -r requirements.txt
    fi
fi

# 4. Launch 2501
echo "Starting 2501..."
$PYTHON_CMD 2501.py "$@"
