# Home Agent

An AI-driven home automation system using Matter-over-Thread and local LLM reasoning.

## Documentation
- [Architecture Overview](ARCHITECTURE.md): High-level system design and components.
- [Task List](task.md): Project roadmap and progress.

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
Run the comprehensive test suite (pytest):
```bash
python -m pytest tests/
```
Or run specific tests:
```bash
python -m pytest tests/test_e2e_integration.py
```

## Directory Structure
- `agent/`: Core source code (Event Bus, State, Mission, Dialogue, etc.).
- `config/`: Configuration files (YAML).
- `docs/`: Additional documentation.
- `tests/`: Unit and Integration tests.

