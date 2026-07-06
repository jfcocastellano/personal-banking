"""Shared pytest fixtures for unit tests."""

import secrets
from pathlib import Path

import pytest


@pytest.fixture
def valid_master_key() -> str:
    """Return a valid 64-character hex MasterKey string."""
    return secrets.token_hex(32)


@pytest.fixture
def mock_master_key(monkeypatch: pytest.MonkeyPatch, valid_master_key: str) -> str:
    """Set BANKING_MASTER_KEY in the environment and return its value."""
    monkeypatch.setenv("BANKING_MASTER_KEY", valid_master_key)
    return valid_master_key


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """Return a temporary .env file path (file does not exist yet)."""
    return tmp_path / ".env"
