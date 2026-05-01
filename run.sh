#!/bin/bash

#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "--- 2501 DeepMemory Launcher ---"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if requirements are installed
if ! python -c "import httpx" &> /dev/null; then
    echo "Installing requirements..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install requirements."
        exit 1
    fi
fi

# Run the application
echo "Starting 2501..."
python 2501.py "$@"
