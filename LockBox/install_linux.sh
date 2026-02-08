#!/bin/bash

# Check if python3 exists
if ! command -v python3 &> /dev/null; then
    echo "[LockBox] Python3 not found. Attempting to install..."
    
    # Detect Package Manager and install
    if [ -x "$(command -v apk)" ]; then
        echo "Detected Alpine (apk). Installing..."
        sudo apk add --no-cache python3
    elif [ -x "$(command -v apt-get)" ]; then
        echo "Detected Debian/Ubuntu (apt). Installing..."
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv
    elif [ -x "$(command -v dnf)" ]; then
        echo "Detected Fedora/RHEL (dnf). Installing..."
        sudo dnf install -y python3
    elif [ -x "$(command -v pacman)" ]; then
        echo "Detected Arch (pacman). Installing..."
        sudo pacman -S --noconfirm python
    elif [ -x "$(command -v yum)" ]; then
        echo "Detected CentOS (yum). Installing..."
        sudo yum install -y python3
    else
        echo "Error: Could not detect a supported package manager."
        echo "Please install Python 3.8+ manually."
        exit 1
    fi
    
    echo "[LockBox] Python3 installed."
fi

# Hand off to the Python installer script
python3 install.py