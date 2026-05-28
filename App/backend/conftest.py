"""Pytest fixtures.

Each test gets its own fresh SQLite DB at a tempfile path. The Flask
app reads DATABASE_PATH from os.environ at connection time
(see database.py), so we override it before importing the app.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db_path(monkeypatch):
    """Per-test scratch SQLite DB file. Cleaned up on teardown."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_PATH", path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("MEDICAL_PASSWORD", "med-pw")
    monkeypatch.setenv("GOV_PASSWORD", "gov-pw")
    monkeypatch.setenv("DEVICE_SECRET", "test-device-secret")
    monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURES", "false")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture()
def app(tmp_db_path):
    """Fresh Flask app bound to the scratch DB. Re-imports so module
    state (DEMO_USERS, init_db) is rebuilt against the new env."""
    for mod in ("app", "database", "labels", "sensor_ingest"):
        sys.modules.pop(mod, None)
    import app as app_mod
    return app_mod.app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def gov_session(client):
    """Test client with the government user signed in."""
    client.post("/login", data={"username": "official.jones", "password": "gov-pw"})
    return client


@pytest.fixture()
def med_session(client):
    """Test client with the medical user signed in."""
    client.post("/login", data={"username": "dr.smith", "password": "med-pw"})
    return client
