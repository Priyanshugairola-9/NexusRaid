"""Shared test setup.

Settings and the database engine are created when the app is first imported,
so the environment variables below must be set BEFORE any app import. The
FastAPI client is imported inside its fixture, so the analysis-engine tests
can run even where only pandas/numpy/scikit-learn are installed.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="nexusraid-test-"))
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)

os.environ["NEXUSRAID_ENVIRONMENT"] = "development"
os.environ["NEXUSRAID_DATABASE_URL"] = f"sqlite:///{(_TEST_DATA_DIR / 'test.db').as_posix()}"
os.environ["NEXUSRAID_UPLOAD_DIR"] = str(_TEST_DATA_DIR / "uploads")
os.environ["NEXUSRAID_CORS_ORIGINS"] = "http://localhost:5173"
os.environ["NEXUSRAID_AGENT_TOKEN"] = "test-agent-token"
os.environ["NEXUSRAID_ACCESS_KEY"] = ""
os.environ["NEXUSRAID_MAX_UPLOAD_MB"] = "2"
os.environ["NEXUSRAID_FRONTEND_DIST"] = str(_TEST_DATA_DIR / "no-frontend")

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    # "with" runs the startup code (folders + tables) like a real server.
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def samples_dir():
    return SAMPLES_DIR
