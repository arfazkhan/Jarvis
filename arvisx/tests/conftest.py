def pytest_configure(config):
    # Golden-eval online mode (needs a live LLM key). Deselect in CI with -m "not online".
    config.addinivalue_line(
        "markers", "online: exercises a real LLM provider; skipped unless run explicitly")
