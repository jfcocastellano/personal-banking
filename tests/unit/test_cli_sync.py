"""Tests for the `banking sync` CLI subcommand (in-process, run_sync mocked)."""

import argparse

import pytest

from banking.cli import sync as cli_sync
from banking.sync import IngSyncError, SheetsSyncError, SyncResult


def test_handle_success_prints_summary_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli_sync,
        "run_sync",
        lambda: SyncResult(
            bank_name="ING España", rows_written=12, tab_name="2026-08", duration_seconds=3.42
        ),
    )

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "ING España" in captured.out
    assert "12" in captured.out
    assert "2026-08" in captured.out
    assert "3.42" in captured.out


def test_handle_ing_failure_prints_stderr_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise() -> None:
        raise IngSyncError("re-auth needed")

    monkeypatch.setattr(cli_sync, "run_sync", _raise)

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ing" in captured.err.lower()
    assert "re-auth needed" in captured.err


def test_handle_sheets_failure_prints_stderr_and_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise() -> None:
        raise SheetsSyncError("no access")

    monkeypatch.setattr(cli_sync, "run_sync", _raise)

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sheets" in captured.err.lower()
    assert "no access" in captured.err
