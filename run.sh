#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "--- 2501 DeepMemory Launcher (Portable) ---"

# Check if requirements are installed (heuristic: check if bs4 is available)
# We check both global python and our local libs folder
if ! python3 -c "import sys; sys.path.insert(0, './libs'); import bs4" &> /dev/null; then
    echo "Installing requirements into local 'libs' folder..."
    mkdir -p libs
    pip3 install --target ./libs -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install requirements."
        exit 1
    fi
fi

# Run the application
echo "Starting 2501..."
python3 2501.py "$@"
