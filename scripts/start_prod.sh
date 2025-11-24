#!/bin/bash
# Production startup script for Home Agent

echo "🚀 Starting Home Agent in Production Mode..."

# Check if running as service
if [ "$1" != "--service" ]; then
    echo "⚠️  Warning: For production, run as systemd service"
    echo "   Use: systemctl start home-agent"
fi

# Activate virtual environment
if [ ! -d "venv" ]; then
    echo "❌ No virtual environment found. Run: python -m venv venv && pip install -r requirements.txt"
    exit 1
fi

source venv/bin/activate

# Validate environment
if [ ! -f ".env" ]; then
    echo "❌ No .env file found"
    exit 1
fi

source .env

if [ -z "$GROQ_API_KEY" ]; then
    echo "❌ GROQ_API_KEY not set in .env"
    exit 1
fi

# Create data directories
mkdir -p data/memory
mkdir -p data/cognitive
mkdir -p agent/logs

# Run with production settings
echo "🏃 Starting agent in production mode..."
export ENV=production
export DEBUG=false
python -m agent.main
