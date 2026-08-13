"""Tests for the `banking sync` CLI subcommand (in-process, run_sync mocked)."""

import argparse

import pytest

from banking.cli import sync as cli_sync
from banking.sync import (
    AllBanksFailedError,
    BankOutcome,
    OverallStatus,
    SheetsSyncError,
    SyncSummary,
)

_BANKS = ["ING España", "Revolut", "MyInvestor", "Banco Sabadell"]


def _summary(overall_status: OverallStatus, outcomes: list[BankOutcome]) -> SyncSummary:
    total_rows = sum(o.rows_written or 0 for o in outcomes)
    return SyncSummary(
        outcomes=outcomes,
        overall_status=overall_status,
        tab_name="2026-08",
        total_rows_written=total_rows,
        duration_seconds=3.42,
    )


def _full_success_summary() -> SyncSummary:
    outcomes = [
        BankOutcome(bank_name=name, succeeded=True, rows_written=n, failure_reason=None)
        for name, n in zip(_BANKS, [3, 2, 1, 4], strict=True)
    ]
    return _summary(OverallStatus.FULL_SUCCESS, outcomes)


def test_handle_full_success_prints_summary_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_sync, "run_sync", lambda: _full_success_summary())

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "4/4" in captured.out
    assert "10" in captured.out  # total de movimientos: 3+2+1+4
    assert "2026-08" in captured.out
    assert "3.42" in captured.out
    for name in _BANKS:
        assert name in captured.out


def _partial_failure_summary() -> SyncSummary:
    outcomes = [
        BankOutcome(bank_name="ING España", succeeded=True, rows_written=3, failure_reason=None),
        BankOutcome(
            bank_name="Revolut", succeeded=False, rows_written=None, failure_reason="re-auth needed"
        ),
        BankOutcome(bank_name="MyInvestor", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(
            bank_name="Banco Sabadell", succeeded=True, rows_written=4, failure_reason=None
        ),
    ]
    return _summary(OverallStatus.PARTIAL_FAILURE, outcomes)


def test_handle_partial_failure_prints_summary_and_exits_three(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_sync, "run_sync", lambda: _partial_failure_summary())

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 3
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "3/4" in captured.out
    assert "Revolut" in captured.out
    assert "re-auth needed" in captured.out
    assert "8" in captured.out  # total escrito: 3+1+4


def test_handle_all_banks_failed_prints_stderr_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise() -> None:
        raise AllBanksFailedError(
            "ING España: ing boom; Revolut: revolut boom; MyInvestor: myinvestor boom; "
            "Banco Sabadell: sabadell boom"
        )

    monkeypatch.setattr(cli_sync, "run_sync", _raise)

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    for name in _BANKS:
        assert name in captured.err


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
