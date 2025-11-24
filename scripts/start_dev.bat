@echo off
REM Development startup script for Home Agent (Windows)

echo Starting Home Agent in Development Mode...

REM Activate virtual environment
if exist "venv\" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo No virtual environment found. Creating one...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
)

REM Check environment variables
if not exist ".env" (
    echo No .env file found. Creating from .env.example...
    copy .env.example .env
    echo Please update .env with your API keys
    exit /b 1
)

REM Create data directories
echo Creating data directories...
if not exist "data\memory" mkdir data\memory
if not exist "data\cognitive" mkdir data\cognitive
if not exist "agent\logs" mkdir agent\logs

REM Run the agent
echo Starting agent...
set ENV=development
set DEBUG=true
python -m agent.main
