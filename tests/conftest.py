"""
Test configuration for OryaAgent.

MVP phase: bootstrap project structure.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app


# FastAPI test client for all tests
@pytest.fixture(scope="session")
def client():
    """FastAPI test client."""
    with TestClient(app) as client:
        yield client


# Event loop for async tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
