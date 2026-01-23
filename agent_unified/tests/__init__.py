"""
ARVIS Test Suite - __init__.py
================================

Test package initialization.
"""

# Test configuration
ASYNC_TEST_TIMEOUT = 30  # seconds

# Mark all tests as requiring async
import pytest

# Register pytest markers
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
