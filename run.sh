#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "--- 2501 DeepMemory Launcher ---"

# Try to create virtual environment
if [ ! -f "venv/bin/activate" ] && [ ! -d "libs" ]; then
    echo "Attempting to create virtual environment..."
    rm -rf venv
    # Try with --copies for USB compatibility
    if python3 -m venv --copies venv 2>/dev/null; then
        echo "Virtual environment created successfully."
    else
        echo "Note: venv creation failed (likely due to USB file system limits)."
        echo "Falling back to 'libs' folder mode..."
        rm -rf venv
        mkdir -p libs
    fi
fi

# Activate environment or setup libs path
if [ -f "venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
    PYTHON_CMD="python3"
else
    echo "Using system python with local libs..."
    PYTHON_CMD="python3"
    export PYTHONPATH="$PYTHONPATH:$(pwd)/libs"
fi

# Check if requirements are installed
if ! $PYTHON_CMD -c "import httpx" &> /dev/null; then
    echo "Installing requirements..."
    if [ -f "venv/bin/activate" ]; then
        $PYTHON_CMD -m pip install -r requirements.txt
    else
        $PYTHON_CMD -m pip install -t libs -r requirements.txt
    fi
    
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install requirements."
        exit 1
    fi
fi

# Run the application
echo "Starting 2501..."
$PYTHON_CMD 2501.py "$@"
