"""Tests for the `banking secrets set` CLI subcommand."""

import os
import subprocess
import sys
from pathlib import Path


def _base_env(tmp_env_file: Path, master_key: str) -> dict[str, str]:
    """Build a subprocess env that inherits the current env with overrides."""
    env = dict(os.environ)
    env["BANKING_MASTER_KEY"] = master_key
    env["BANKING_ENV_FILE"] = str(tmp_env_file)
    return env


def test_secrets_set_writes_encrypted_value(mock_master_key: str, tmp_env_file: Path) -> None:
    """secrets set writes an enc: prefixed entry to the .env file."""
    result = subprocess.run(
        [sys.executable, "-m", "banking", "secrets", "set", "TEST_KEY", "secret_value"],
        capture_output=True,
        text=True,
        env=_base_env(tmp_env_file, mock_master_key),
    )
    assert result.returncode == 0, result.stderr
    content = tmp_env_file.read_text()
    assert "TEST_KEY=enc:" in content


def test_secrets_set_does_not_write_plaintext(mock_master_key: str, tmp_env_file: Path) -> None:
    """secrets set must not write plaintext value to .env file."""
    plaintext = "super_secret_password_123"
    result = subprocess.run(
        [sys.executable, "-m", "banking", "secrets", "set", "MY_KEY", plaintext],
        capture_output=True,
        text=True,
        env=_base_env(tmp_env_file, mock_master_key),
    )
    assert result.returncode == 0, result.stderr
    content = tmp_env_file.read_text()
    assert plaintext not in content


def test_secrets_set_missing_master_key_exits_one(tmp_env_file: Path) -> None:
    """secrets set with missing BANKING_MASTER_KEY exits with code 1."""
    env = dict(os.environ)
    env.pop("BANKING_MASTER_KEY", None)
    env["BANKING_ENV_FILE"] = str(tmp_env_file)
    result = subprocess.run(
        [sys.executable, "-m", "banking", "secrets", "set", "KEY", "value"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "BANKING_MASTER_KEY" in result.stderr


def test_secrets_set_missing_args_exits_nonzero(mock_master_key: str) -> None:
    """secrets set with missing KEY or VALUE args exits non-zero."""
    env = dict(os.environ)
    env["BANKING_MASTER_KEY"] = mock_master_key
    result = subprocess.run(
        [sys.executable, "-m", "banking", "secrets", "set"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
