#!/bin/bash
# Move to the project directory
cd "/root/Desktop/agy-mobile"

# Print message
echo "Starting AGY Workspace Chat Server..."

# Run the server using the virtual environment's python
./venv/bin/python main.py

# Keep terminal open on exit to view errors/status
echo ""
echo "Server stopped."
read -p "Press Enter to exit..."
