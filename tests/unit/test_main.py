"""Tests for the banking package entry point (__main__.py)."""

import subprocess
import sys


def test_entry_point_no_args_exits_zero() -> None:
    """Running `python -m banking` with no args prints usage and exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "banking"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout.lower()
    assert "secrets" in result.stdout


def test_entry_point_unknown_subcommand_exits_nonzero() -> None:
    """Running `python -m banking unknown` exits with a non-zero code."""
    result = subprocess.run(
        [sys.executable, "-m", "banking", "unknown_subcommand"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
