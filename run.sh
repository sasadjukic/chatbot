#!/bin/bash

# Navigate to the script directory
cd "$(dirname "$0")"

echo "=== Antigravity Chatbot Startup ==="

# Check if virtualenv exists
if [ -d "bin" ] && [ -f "bin/activate" ]; then
    echo "Activating virtual environment..."
    source bin/activate
elif [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo "Activating virtual environment (venv)..."
    source venv/bin/activate
else
    echo "Virtual environment not detected in root directory."
    echo "Creating a new virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
fi

# Install dependencies
echo "Installing/upgrading dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Free port 8000 if already in use
PORT=8000
if command -v lsof >/dev/null 2>&1; then
    PID=$(lsof -t -i:$PORT)
    if [ ! -z "$PID" ]; then
        echo "Port $PORT is already in use by PID(s): $PID. Terminating process..."
        kill -9 $PID 2>/dev/null || true
        sleep 1
    fi
elif command -v fuser >/dev/null 2>&1; then
    echo "Port $PORT is already in use. Terminating process..."
    fuser -k $PORT/tcp >/dev/null 2>&1 || true
    sleep 1
fi

# Launch FastAPI app
echo "Starting FastAPI server on http://localhost:8000 ..."
python main.py
