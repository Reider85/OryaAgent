"""
Test configuration for OryaAgent.

MVP phase: bootstrap project structure.
"""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

# A-20: the connection-pool health worker must never probe real providers
# from a test lifespan. The non-ORYA spelling survives the standard
# ``ORYA_*`` env sandboxes, so the session ``client`` fixture keeps it.
os.environ.setdefault("LLM_POOL_HEALTH_INTERVAL", "0")

from app.main import app  # noqa: E402 - env must be set before import


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
