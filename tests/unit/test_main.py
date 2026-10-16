"""Tests for the banking package entry point (__main__.py)."""

import os
import re
import subprocess
import sys
from pathlib import Path

from banking.__main__ import _build_parser


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
    assert "sync" in result.stdout


def test_sync_subcommand_is_registered() -> None:
    """`sync` parses as a known subcommand — never invokes the real pipeline."""
    args = _build_parser().parse_args(["sync"])
    assert args.command == "sync"


def test_entry_point_unknown_subcommand_exits_nonzero() -> None:
    """Running `python -m banking unknown` exits with a non-zero code."""
    result = subprocess.run(
        [sys.executable, "-m", "banking", "unknown_subcommand"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_cli_configures_logging_so_records_reach_stderr(tmp_path: Path) -> None:
    """The entry point must configure logging, not just create loggers.

    Runs the real CLI without any usable bank configuration, so all four
    connectors fail before any network call, then asserts the error record
    reaches stderr in the format mandated by the constitution. Without an
    entry-point ``configure_logging`` call the root logger has no handler and
    every record is silently discarded.
    """
    env = dict(os.environ)
    env["BANKING_EB_CONFIG_DIR"] = str(tmp_path / "missing-config-dir")
    env["BANKING_ENV_FILE"] = str(tmp_path / "missing.env")
    env.pop("LOG_LEVEL", None)

    result = subprocess.run(
        [sys.executable, "-m", "banking", "sync"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ERROR banking\.sync: ",
        result.stderr,
        re.MULTILINE,
    ), f"no formatted ERROR record on stderr:\n{result.stderr}"
