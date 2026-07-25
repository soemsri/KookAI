#!/bin/bash
# Always run from the directory containing this script.
cd -- "$(dirname -- "$0")"

# Print message
echo "Starting KookAI Workspace Chat Server..."

# Run the server using the virtual environment's python
./venv/bin/python main.py

# Keep terminal open on exit to view errors/status
echo ""
echo "Server stopped."
read -p "Press Enter to exit..."
