# Home Agent Test Suite

Comprehensive test suite covering 112+ failure scenarios across 12 categories.

## Running Tests

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run All Tests
```bash
pytest tests/ -v
```

### Run with Coverage
```bash
pytest tests/ --cov=agent --cov-report=html
```

Open `htmlcov/index.html` to view detailed coverage report.

### Run Specific Category
```bash
# Event Bus failures
pytest tests/test_event_bus_failures.py -v

# LLM failures  
pytest tests/test_llm_agent_failures.py -v

# State Engine
pytest tests/test_state_engine_failures.py -v
```

### Run in Parallel (Faster)
```bash
pytest tests/ -n auto
```

### Run with Timeout Protection
```bash
pytest tests/ --timeout=30
```

### Skip Slow Tests
```bash
pytest tests/ -m "not slow"
```

### Run Only Stress Tests
```bash
pytest tests/ -m stress
```

### Run Only Security Tests
```bash
pytest tests/ -m security
```

## Test Categories

### ✅ Implemented
- **Event Bus Failures** - Ordering, corruption, race conditions (test_event_bus_failures.py)
- **State Engine Failures** - Race conditions, integrity (test_state_engine_failures.py)
- **LLM Agent Failures** - Malformation, hallucinations, JSON corruption (test_llm_agent_failures.py)

### 🚧 Coming Soon
- Learning Engine pattern/drift failures
- Automation Engine execution/schedule tests
- Matter Controller device failures
- Simulation Engine LLM generation tests
- Flask API security tests
- Frontend rendering tests
- Memory leak tests
- System crash tests
- Security attack tests
- Real-world chaos scenarios

## Test Markers

- `@pytest.mark.slow` - Long-running tests
- `@pytest.mark.stress` - High-load stress tests
- `@pytest.mark.security` - Security vulnerability tests
- `@pytest.mark.integration` - Integration tests

## Coverage Goals

- **80%+ overall coverage**
- **100% coverage on critical paths:**
  - Event handling
  - LLM parsing
  - State updates
  - Tool execution

## CI/CD Integration

Tests run automatically on every commit. Build fails if:
- Any test fails
- Coverage drops below 80%
- Security tests fail

## Writing New Tests

Use fixtures from `conftest.py`:

```python
def test_example(event_bus, state_engine):
    """Your test description."""
    from conftest import create_valid_event
    
    event = create_valid_event()
    event_bus.publish(event)
    
    history = state_engine.get_history()
    assert len(history) == 1
```

## Test Helper Functions

From `conftest.py`:

- `create_valid_event()` - Generate valid events
- `create_corrupted_event(type)` - Generate corrupted events
- `create_out_of_order_events(count)` - Out-of-order events
- `create_event_burst(count)` - Large event bursts
- `create_llm_response()` - Mock LLM responses
- `create_pattern_history(type)` - Pattern test data

## Troubleshooting

### Tests hang
- Use `--timeout=30` flag
- Check for infinite loops in test code

### ImportError
- Ensure you're running from project root
- Verify `PYTHONPATH` includes project directory

### Flaky tests
- Tests with threading may be timing-sensitive
- Add appropriate `time.sleep()` or synchronization

### Coverage not generating
- Install coverage: `pip install pytest-cov`
- Ensure tests are passing first

## Performance Benchmarks

Target performance for stress tests:

- 1000 events/second burst: < 2 seconds
- 500 concurrent publishes: < 5 seconds
- 10,000 event history: < 1 second to query
- Pattern clustering on 30 days: < 10 seconds
