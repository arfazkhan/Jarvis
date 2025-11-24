#!/bin/bash
# Development startup script for Home Agent

echo "🚀 Starting Home Agent in Development Mode..."

# Activate virtual environment
if [ -d "venv" ]; then
    echo "✅ Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  No virtual environment found. Creating one..."
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
fi

# Check environment variables
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo "📝 Please update .env with your API keys"
    exit 1
fi

# Create data directories if they don't exist
echo "📁 Creating data directories..."
mkdir -p data/memory
mkdir -p data/cognitive
mkdir -p agent/logs

# Run the agent
echo "🏃 Starting agent..."
export ENV=development
export DEBUG=true
python -m agent.main
