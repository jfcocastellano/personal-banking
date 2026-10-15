"""Tests for the process-wide logging configuration (constitution: Mandatory observability).

The constitution mandates the record format
``%(asctime)s %(levelname)s %(name)s: %(message)s``, so the format is asserted
through a real subprocess and a real stderr stream rather than by inspecting
Python objects: what matters is the text a human reads in the CI log.
"""

import logging
import os
import subprocess
import sys

import pytest

from banking.logging_config import LOG_FORMAT, resolve_level

_EMIT_RECORD = (
    "import logging;"
    "from banking.logging_config import configure_logging;"
    "configure_logging();"
    "logging.getLogger('banking.sync').info('Sync succeeded: status=full_success');"
    "logging.getLogger('banking.sync').debug('debug detail')"
)


def _run_emitting_subprocess(log_level: str | None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess that configures logging the way the CLI does, then emits
    one INFO and one DEBUG record from the ``banking.sync`` logger.
    """
    env = dict(os.environ)
    env.pop("LOG_LEVEL", None)
    if log_level is not None:
        env["LOG_LEVEL"] = log_level
    return subprocess.run(
        [sys.executable, "-c", _EMIT_RECORD],
        capture_output=True,
        text=True,
        env=env,
    )


def test_resolve_level_defaults_to_info_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert resolve_level(None) == logging.INFO


def test_resolve_level_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert resolve_level(None) == logging.DEBUG


def test_resolve_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert resolve_level(None) == logging.WARNING


def test_resolve_level_prefers_explicit_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert resolve_level("DEBUG") == logging.DEBUG


def test_resolve_level_falls_back_to_info_on_unrecognised_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in LOG_LEVEL must never crash the sync run."""
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    assert resolve_level(None) == logging.INFO


def test_format_matches_constitution() -> None:
    assert LOG_FORMAT == "%(asctime)s %(levelname)s %(name)s: %(message)s"


def test_configured_logging_emits_formatted_record_on_stderr() -> None:
    """At DEBUG level, an INFO record reaches stderr with the mandated format."""
    result = _run_emitting_subprocess("DEBUG")

    assert result.returncode == 0
    assert "Sync succeeded: status=full_success" in result.stderr
    assert "DEBUG banking.sync: debug detail" in result.stderr
    assert "INFO banking.sync: Sync succeeded: status=full_success" in result.stderr

    info_line = next(line for line in result.stderr.splitlines() if "INFO banking.sync" in line)
    # e.g. "2026-08-15 10:30:00,123 INFO banking.sync: Sync succeeded: status=full_success"
    assert info_line[:4].isdigit()
    assert info_line[4] == "-"
    assert info_line[19] == ","


def test_configured_logging_defaults_to_info() -> None:
    """With LOG_LEVEL unset the default is INFO: no DEBUG noise, INFO still shown."""
    result = _run_emitting_subprocess(None)

    assert "INFO banking.sync: Sync succeeded: status=full_success" in result.stderr
    assert "debug detail" not in result.stderr


def test_configured_logging_honours_warning_level() -> None:
    """At WARNING level the INFO record is filtered out."""
    result = _run_emitting_subprocess("WARNING")

    assert "Sync succeeded: status=full_success" not in result.stderr
