#!/bin/bash

# Nginx UI Startup Script

echo "Starting Nginx UI..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update requirements
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Set secure secret key if not already set
if [ -z "$SECRET_KEY" ]; then
    export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    echo "Generated random SECRET_KEY for this session"
fi

# Run the application
echo "Starting Flask application on http://0.0.0.0:9000"
echo ""
echo "Default credentials:"
echo "  Username: admin"
echo "  Password: admin"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python app.py

