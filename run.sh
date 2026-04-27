#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "--- 2501 DeepMemory Launcher ---"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment. Do you have python3-venv installed?"
        exit 1
    fi
fi

# Activate virtual environment
source venv/bin/activate

# Check if requirements are installed (heuristic: check if httpx is available)
if ! python3 -c "import httpx" &> /dev/null; then
    echo "Installing requirements..."
    pip install --upgrade pip
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install requirements."
        exit 1
    fi
fi

# Run the application
echo "Starting 2501..."
python3 2501.py "$@"
