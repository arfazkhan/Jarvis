# Home Agent

An AI-driven home automation system using Matter-over-Thread and local LLM reasoning.

## Setup

### 1. Create Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env` file in the root directory (if it doesn't exist) and add your API key:
```ini
GROQ_API_KEY=your_groq_api_key_here
ENV=development
DEBUG=true
```

### 4. Run the Agent
```bash
python -m agent.main
```

## Testing
Run the unit tests to verify everything is working:
```bash
python -m unittest discover tests
```

## Directory Structure
- `agent/`: Core source code.
- `config/`: Configuration files.
- `docs/`: Documentation.
- `tests/`: Unit tests.
