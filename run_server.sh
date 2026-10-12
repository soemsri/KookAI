#!/bin/bash
# Always run from the directory containing this script.
cd -- "$(dirname -- "$0")"

echo "Starting KookAI Workspace Chat Server..."

if [ ! -x "./venv/bin/python" ]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
  if [ -z "$PYTHON_BIN" ]; then
    echo "Python 3.10+ is required but was not found."
    exit 1
  fi
  echo "Creating Python virtual environment..."
  "$PYTHON_BIN" -m venv venv || exit 1
fi

# main.py installs missing Python and CLI requirements on first launch.
while true; do
  ./venv/bin/python main.py
  EXIT_CODE=$?
  echo "Server stopped with exit code $EXIT_CODE. Restarting in 2 seconds..."
  sleep 2
done
