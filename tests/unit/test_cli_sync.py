"""Tests for the `banking sync` CLI subcommand (in-process, run_sync mocked)."""

import argparse

import pytest
from pytest_mock import MockerFixture

from banking.cli import sync as cli_sync
from banking.notify import DeliveryStatus, EmailNotifier
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


# --- IT6 (US1): notificación del fallo parcial -------------------------------


def test_handle_partial_failure_notifies_once_with_the_summary_context(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    summary = _partial_failure_summary()
    monkeypatch.setattr(cli_sync, "run_sync", lambda: summary)
    notifier = mocker.Mock(spec=EmailNotifier)
    notifier.notify_failure.return_value = DeliveryStatus.SENT

    exit_code = cli_sync.handle(argparse.Namespace(), notifier=notifier)

    notifier.notify_failure.assert_called_once_with(
        outcomes=summary.outcomes,
        sheets_error=None,
        tab_name="2026-08",
        duration_seconds=3.42,
    )
    assert exit_code == 3


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        pytest.param(DeliveryStatus.SENT, 3, id="sent"),
        pytest.param(DeliveryStatus.SKIPPED, 3, id="skipped"),
        pytest.param(DeliveryStatus.FAILED, 4, id="failed"),
    ],
)
def test_handle_partial_failure_maps_delivery_status_to_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    status: DeliveryStatus,
    expected_exit: int,
) -> None:
    summary = _partial_failure_summary()
    monkeypatch.setattr(cli_sync, "run_sync", lambda: summary)
    notifier = mocker.Mock(spec=EmailNotifier)
    notifier.notify_failure.return_value = status

    exit_code = cli_sync.handle(argparse.Namespace(), notifier=notifier)

    assert exit_code == expected_exit
    captured = capsys.readouterr()
    # The IT5 run summary is always printed, whatever happens to the email.
    assert "3/4" in captured.out
    if status is DeliveryStatus.FAILED:
        assert "ERROR (notificación): no se pudo enviar el email de aviso" in captured.err
    else:
        assert "notificación" not in captured.err


# --- IT6 (US2): notificación del fallo total y del fallo de Sheets ----------


def _total_failure_exception() -> AllBanksFailedError:
    return AllBanksFailedError(
        "All four banks failed: ING España: ing boom; Revolut: revolut boom; "
        "MyInvestor: myinvestor boom; Banco Sabadell: sabadell boom",
        outcomes=[
            BankOutcome("ING España", False, None, "ing boom"),
            BankOutcome("Revolut", False, None, "revolut boom"),
            BankOutcome("MyInvestor", False, None, "myinvestor boom"),
            BankOutcome("Banco Sabadell", False, None, "sabadell boom"),
        ],
        tab_name="2026-08",
    )


def _sheets_failure_exception() -> SheetsSyncError:
    return SheetsSyncError(
        "no access",
        outcomes=[
            BankOutcome("ING España", True, 3, None),
            BankOutcome("Revolut", False, None, "revolut boom"),
            BankOutcome("MyInvestor", True, 1, None),
            BankOutcome("Banco Sabadell", True, 4, None),
        ],
        tab_name="2026-08",
    )


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        pytest.param(DeliveryStatus.SENT, 1, id="sent"),
        pytest.param(DeliveryStatus.SKIPPED, 1, id="skipped"),
        pytest.param(DeliveryStatus.FAILED, 4, id="failed"),
    ],
)
def test_handle_total_failure_notifies_with_the_exception_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    status: DeliveryStatus,
    expected_exit: int,
) -> None:
    exc = _total_failure_exception()

    def _raise() -> None:
        raise exc

    monkeypatch.setattr(cli_sync, "run_sync", _raise)
    notifier = mocker.Mock(spec=EmailNotifier)
    notifier.notify_failure.return_value = status

    exit_code = cli_sync.handle(argparse.Namespace(), notifier=notifier)

    assert exit_code == expected_exit
    notifier.notify_failure.assert_called_once_with(
        outcomes=exc.outcomes,
        sheets_error=None,
        tab_name="2026-08",
        duration_seconds=0.0,
    )
    captured = capsys.readouterr()
    for name in _BANKS:
        assert name in captured.err
    if status is DeliveryStatus.FAILED:
        assert "ERROR (notificación): no se pudo enviar el email de aviso" in captured.err


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        pytest.param(DeliveryStatus.SENT, 2, id="sent"),
        pytest.param(DeliveryStatus.SKIPPED, 2, id="skipped"),
        pytest.param(DeliveryStatus.FAILED, 4, id="failed"),
    ],
)
def test_handle_sheets_failure_notifies_with_the_sheets_error_and_bank_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    status: DeliveryStatus,
    expected_exit: int,
) -> None:
    exc = _sheets_failure_exception()

    def _raise() -> None:
        raise exc

    monkeypatch.setattr(cli_sync, "run_sync", _raise)
    notifier = mocker.Mock(spec=EmailNotifier)
    notifier.notify_failure.return_value = status

    exit_code = cli_sync.handle(argparse.Namespace(), notifier=notifier)

    assert exit_code == expected_exit
    notifier.notify_failure.assert_called_once_with(
        outcomes=exc.outcomes,
        sheets_error="no access",
        tab_name="2026-08",
        duration_seconds=0.0,
    )
    captured = capsys.readouterr()
    assert "ERROR (Sheets): no access" in captured.err
    if status is DeliveryStatus.FAILED:
        assert "ERROR (notificación): no se pudo enviar el email de aviso" in captured.err


def test_handle_failure_without_context_falls_back_to_empty_outcomes_and_current_tab(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """An older caller raising without context must still notify, never crash."""
    from datetime import date

    def _raise() -> None:
        raise AllBanksFailedError("boom")

    monkeypatch.setattr(cli_sync, "run_sync", _raise)
    notifier = mocker.Mock(spec=EmailNotifier)
    notifier.notify_failure.return_value = DeliveryStatus.SENT

    exit_code = cli_sync.handle(argparse.Namespace(), notifier=notifier)

    assert exit_code == 1
    kwargs = notifier.notify_failure.call_args.kwargs
    assert kwargs["outcomes"] == []
    assert kwargs["sheets_error"] is None
    assert kwargs["tab_name"] == date.today().strftime("%Y-%m")


# --- IT6 (US3): ningún email cuando todo va bien ----------------------------


@pytest.mark.parametrize(
    "summary",
    [
        pytest.param(_full_success_summary(), id="rows-written"),
        pytest.param(
            _summary(
                OverallStatus.FULL_SUCCESS,
                [BankOutcome(name, True, 0, None) for name in _BANKS],
            ),
            id="zero-movements",
        ),
    ],
)
def test_handle_full_success_never_notifies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    summary: SyncSummary,
) -> None:
    monkeypatch.setattr(cli_sync, "run_sync", lambda: summary)
    notifier = mocker.Mock(spec=EmailNotifier)

    exit_code = cli_sync.handle(argparse.Namespace(), notifier=notifier)

    assert exit_code == 0
    notifier.notify_failure.assert_not_called()
    assert capsys.readouterr().err == ""


def test_handle_full_success_does_not_even_build_a_notifier(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """No SMTP configuration is read on the happy path (FR-003)."""
    monkeypatch.setattr(cli_sync, "run_sync", lambda: _full_success_summary())
    exploding = mocker.patch.object(cli_sync, "EmailNotifier", autospec=True)
    exploding.side_effect = AssertionError("EmailNotifier must not be built on success")

    exit_code = cli_sync.handle(argparse.Namespace())

    assert exit_code == 0
