"""Tests for the `banking daily` CLI subcommand (in-process, no network).

``run_daily`` is always replaced by a fake and ``EmailNotifier`` by a mock, so a
test that reached a bank API, a real spreadsheet or SMTP would be a bug here.
"""

import argparse
import json
import smtplib
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from banking.__main__ import _build_parser
from banking.cli import daily as cli_daily
from banking.connectors.enable_banking import Balance, Transaction
from banking.daily import BankPass, DailySheetsError, DailySummary, NoBankFetchedError
from banking.notify import DeliveryStatus, EmailNotifier
from banking.sync import OverallStatus

_BANK_A = "ING España"
_BANK_B = "Revolut"
_BANK_C = "MyInvestor"
_NOTIFICATION_FAILED = "ERROR (notificación): no se pudo enviar el email de aviso"


def _transaction(description: str = "Compra", amount: str = "-10.00") -> Transaction:
    return Transaction(
        booking_date=date(2026, 11, 5),
        amount=Decimal(amount),
        currency="EUR",
        description=description,
    )


def _balance(amount: str = "1234.50", reference_date: date | None = date(2026, 11, 20)) -> Balance:
    return Balance(
        amount=Decimal(amount),
        currency="EUR",
        balance_type="CLBD",
        reference_date=reference_date,
    )


def _pass(
    bank_name: str,
    *,
    transactions: tuple[Transaction, ...] = (),
    balance: Balance | None = None,
    transactions_failure: str | None = None,
    balance_failure: str | None = None,
    not_onboarded: bool = False,
) -> BankPass:
    return BankPass(
        bank_name=bank_name,
        transactions=transactions,
        balance=balance,
        transactions_failure=transactions_failure,
        balance_failure=balance_failure,
        not_onboarded=not_onboarded,
    )


def _summary(
    status: OverallStatus,
    passes: list[BankPass],
    *,
    raw_rows: int | None = None,
    expense_rows: int | None = None,
    balance_rows: int | None = None,
    duration: float = 3.42,
) -> DailySummary:
    rows = sum(len(run.transactions) for run in passes)
    return DailySummary(
        passes=passes,
        overall_status=status,
        raw_tab_name="2026-11",
        layout_tab_name="2026-11 Gastos",
        total_rows_written=rows if raw_rows is None else raw_rows,
        expense_count=rows if expense_rows is None else expense_rows,
        balance_count=len(passes) if balance_rows is None else balance_rows,
        duration_seconds=duration,
    )


def _full_success_summary() -> DailySummary:
    return _summary(
        OverallStatus.FULL_SUCCESS,
        [
            _pass(
                _BANK_A,
                transactions=(_transaction("Nómina", "1500.00"), _transaction("Café", "-3.00")),
                balance=_balance("1234.50"),
            ),
            _pass(
                _BANK_B,
                transactions=(_transaction("Suscripción", "-9.99"),),
                balance=_balance("80.00"),
            ),
        ],
    )


def _partial_failure_summary() -> DailySummary:
    return _summary(
        OverallStatus.PARTIAL_FAILURE,
        [
            _pass(
                _BANK_A,
                transactions=(_transaction("Nómina", "1500.00"),),
                balance=_balance("1234.50"),
            ),
            _pass(
                _BANK_B,
                transactions_failure="re-auth needed",
                balance_failure="re-auth needed",
            ),
        ],
    )


def _not_onboarded_summary() -> DailySummary:
    return _summary(
        OverallStatus.NOTHING_TO_SYNC,
        [
            _pass(_BANK_A, not_onboarded=True),
            _pass(_BANK_B, not_onboarded=True),
        ],
        raw_rows=0,
        expense_rows=0,
        balance_rows=0,
    )


def _raise(exc: BaseException) -> object:
    def _raiser() -> None:
        raise exc

    return _raiser


def _mock_notifier(mocker: MockerFixture, status: DeliveryStatus = DeliveryStatus.SENT) -> object:
    notifier = mocker.Mock(spec=EmailNotifier)
    notifier.notify_failure.return_value = status
    return notifier


def _recording_notifier(mocker: MockerFixture) -> tuple[EmailNotifier, smtplib.SMTP]:
    """Build the real notifier with a fake SMTP transport that records the message."""
    values = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "465",
        "SMTP_USER": "bot@example.com",
        "SMTP_PASSWORD": "app-password-1234",
        "NOTIFY_EMAIL_TO": "owner@example.com",
    }
    store = mocker.Mock()
    store.get.side_effect = values.__getitem__
    smtp = mocker.Mock(spec=smtplib.SMTP)
    notifier = EmailNotifier(store=store, smtp_factory=mocker.Mock(return_value=smtp))
    mocker.spy(notifier, "notify_failure")
    return notifier, smtp


def _install_notifier(monkeypatch: pytest.MonkeyPatch, notifier: object) -> None:
    monkeypatch.setattr(cli_daily, "EmailNotifier", lambda: notifier)


def _explode_on_notifier_build(monkeypatch: pytest.MonkeyPatch) -> None:
    def _build() -> None:
        raise AssertionError("EmailNotifier must not be built")

    monkeypatch.setattr(cli_daily, "EmailNotifier", _build)


def _daily_args(path: Path | None = None) -> argparse.Namespace:
    """Parse real ``daily`` argv, optionally with the ``--summary-json`` flag."""
    argv = ["daily"] if path is None else ["daily", "--summary-json", str(path)]
    return _build_parser().parse_args(argv)


# --- registration and parser ------------------------------------------------


def test_daily_appears_in_the_top_level_usage_listing() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "banking"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily" in result.stdout
    assert "sync" in result.stdout
    assert "layout" in result.stdout


def test_daily_subcommand_is_registered_and_takes_no_arguments() -> None:
    args = _build_parser().parse_args(["daily"])

    assert args.command == "daily"
    assert not hasattr(args, "month")


# --- exit code 0: full success and nothing to sync --------------------------


def test_full_success_prints_both_tabs_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = _full_success_summary()
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    _explode_on_notifier_build(monkeypatch)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert summary.raw_tab_name in captured.out
    assert summary.layout_tab_name in captured.out
    assert _BANK_A in captured.out
    assert _BANK_B in captured.out
    assert "3 movimientos" in captured.out
    assert "1234.50" in captured.out
    assert "2026-11-20" in captured.out


def test_full_success_never_builds_a_notifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_daily, "run_daily", lambda: _full_success_summary())
    _explode_on_notifier_build(monkeypatch)

    assert cli_daily.handle(SimpleNamespace()) == 0


def test_nothing_to_sync_prints_the_skip_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    summary = _not_onboarded_summary()
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    notifier = _mock_notifier(mocker)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 0
    notifier.notify_failure.assert_not_called()
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "omitida" in captured.out
    assert "no se ha escrito nada" in captured.out
    assert summary.raw_tab_name in captured.out
    assert summary.layout_tab_name in captured.out
    assert "FALLÓ" not in captured.out


# --- exit code 1: total failure ---------------------------------------------


def _total_failure_exception() -> NoBankFetchedError:
    return NoBankFetchedError(
        "All 2 banks failed: ING España: ing boom; Revolut: revolut boom",
        passes=[
            _pass(_BANK_A, transactions_failure="ing boom", balance_failure="ing boom"),
            _pass(_BANK_B, transactions_failure="revolut boom", balance_failure="revolut boom"),
        ],
        raw_tab_name="2026-11",
        layout_tab_name="2026-11 Gastos",
    )


def test_total_failure_exits_one_and_notifies_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    exc = _total_failure_exception()
    monkeypatch.setattr(cli_daily, "run_daily", _raise(exc))
    notifier = _mock_notifier(mocker)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 1
    notifier.notify_failure.assert_called_once()
    kwargs = notifier.notify_failure.call_args.kwargs
    assert kwargs["tab_name"] == "2026-11"
    assert kwargs["sheets_error"] is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ing boom" in captured.err
    assert "revolut boom" in captured.err


# --- exit code 2: Sheets failure --------------------------------------------


@pytest.mark.parametrize(
    ("stage", "tab_name"),
    [
        pytest.param("raw", "2026-11", id="raw"),
        pytest.param("layout", "2026-11 Gastos", id="layout"),
    ],
)
def test_sheets_failure_exits_two_and_names_the_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    stage: str,
    tab_name: str,
) -> None:
    exc = DailySheetsError(
        "no access",
        stage=stage,
        passes=[_pass(_BANK_A, transactions=(_transaction(),), balance=_balance())],
        tab_name=tab_name,
    )
    monkeypatch.setattr(cli_daily, "run_daily", _raise(exc))
    notifier = _mock_notifier(mocker)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 2
    notifier.notify_failure.assert_called_once()
    kwargs = notifier.notify_failure.call_args.kwargs
    assert stage in kwargs["sheets_error"]
    assert kwargs["tab_name"] == tab_name
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Sheets" in captured.err
    assert stage in captured.err
    assert "no access" in captured.err


# --- exit code 3: partial failure -------------------------------------------


def test_partial_failure_exits_three_and_notifies_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    summary = _partial_failure_summary()
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    notifier = _mock_notifier(mocker, DeliveryStatus.SENT)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 3
    notifier.notify_failure.assert_called_once()
    kwargs = notifier.notify_failure.call_args.kwargs
    assert kwargs["tab_name"] == summary.raw_tab_name
    assert kwargs["sheets_error"] is None
    assert kwargs["duration_seconds"] == summary.duration_seconds
    captured = capsys.readouterr()
    assert _BANK_B in captured.out
    assert "re-auth needed" in captured.out


# --- exit code 4: the notification could not be delivered -------------------


def test_partial_failure_with_failed_delivery_exits_four(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    monkeypatch.setattr(cli_daily, "run_daily", lambda: _partial_failure_summary())
    notifier = _mock_notifier(mocker, DeliveryStatus.FAILED)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 4
    notifier.notify_failure.assert_called_once()
    assert _NOTIFICATION_FAILED in capsys.readouterr().err


@pytest.mark.parametrize(
    ("exc", "base_exit"),
    [
        pytest.param(_total_failure_exception(), 1, id="total"),
        pytest.param(
            DailySheetsError("no access", stage="raw", tab_name="2026-11"), 2, id="sheets"
        ),
    ],
)
def test_other_failures_with_failed_delivery_exit_four(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    exc: BaseException,
    base_exit: int,
) -> None:
    monkeypatch.setattr(cli_daily, "run_daily", _raise(exc))
    notifier = _mock_notifier(mocker, DeliveryStatus.FAILED)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 4
    assert base_exit != exit_code
    assert _NOTIFICATION_FAILED in capsys.readouterr().err


# --- per-bank report --------------------------------------------------------


def test_report_prints_sin_sesion_psd2_and_the_balance_reference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    summary = _summary(
        OverallStatus.FULL_SUCCESS,
        [
            _pass(
                _BANK_A,
                transactions=(_transaction(),),
                balance=_balance("1234.50", date(2026, 11, 20)),
            ),
            _pass(
                _BANK_B,
                transactions=(_transaction("Café", "-3.00"),),
                balance=_balance("80.00", None),
            ),
            _pass(_BANK_C, not_onboarded=True),
        ],
    )
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    notifier = _mock_notifier(mocker)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 0
    notifier.notify_failure.assert_not_called()
    out = capsys.readouterr().out
    assert "SIN SESIÓN PSD2" in out
    assert _BANK_C in out
    assert summary.raw_tab_name in out
    assert summary.layout_tab_name in out
    assert "1234.50" in out
    assert "2026-11-20" in out
    assert "sin dato de referencia" in out


def test_report_keeps_a_balance_failure_visible_without_failing_the_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = _summary(
        OverallStatus.FULL_SUCCESS,
        [
            _pass(
                _BANK_A,
                transactions=(_transaction(),),
                balance_failure="quota exceeded",
            )
        ],
    )
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    _explode_on_notifier_build(monkeypatch)

    exit_code = cli_daily.handle(SimpleNamespace())

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "FALLÓ la consulta de saldo" in out
    assert "quota exceeded" in out


# --- the failure email never drops a balance failure -------------------------


def test_email_names_a_balance_failure_of_a_succeeded_bank(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """A balance failure still counts as success, but the email must say so."""
    summary = _summary(
        OverallStatus.PARTIAL_FAILURE,
        [
            _pass(_BANK_A, transactions=(_transaction(),), balance_failure="quota exceeded"),
            _pass(
                _BANK_B,
                transactions_failure="re-auth needed",
                balance_failure="re-auth needed",
            ),
            _pass(_BANK_C, transactions=(_transaction("Café", "-3.00"),), balance=_balance()),
        ],
    )
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    notifier, smtp = _recording_notifier(mocker)
    _install_notifier(monkeypatch, notifier)

    exit_code = cli_daily.handle(SimpleNamespace())

    # The classification is unchanged: the balance failure does not move the
    # run out of partial failure.
    assert exit_code == 3
    notifier.notify_failure.assert_called_once()
    outcomes = {
        outcome.bank_name: outcome
        for outcome in notifier.notify_failure.call_args.kwargs["outcomes"]
    }
    balance_failed = outcomes[_BANK_A]
    assert balance_failed.succeeded is True
    assert balance_failed.failure_reason is not None
    assert "saldo no disponible" in balance_failed.failure_reason
    assert "quota exceeded" in balance_failed.failure_reason
    # A clean bank still carries no reason, and a real failure keeps its own.
    assert outcomes[_BANK_C].failure_reason is None
    assert outcomes[_BANK_B].failure_reason == "re-auth needed"

    # The rendered email is the end of the chain, not just the notifier payload.
    body = smtp.send_message.call_args.args[0].get_content()
    assert (
        "  - ING España: 1 movimientos — saldo no disponible: quota exceeded" in body.splitlines()
    )


# --- --summary-json: the JSON run summary -----------------------------------


def test_summary_json_flag_writes_the_document_and_leaves_stdout_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The flag is presentation only: same stdout, plus one JSON document."""
    monkeypatch.setattr(cli_daily, "run_daily", lambda: _full_success_summary())
    _explode_on_notifier_build(monkeypatch)
    path = tmp_path / "summary.json"

    assert cli_daily.handle(_daily_args()) == 0
    without_flag = capsys.readouterr()
    assert not path.exists(), "A run without the flag must write no file"

    assert cli_daily.handle(_daily_args(path)) == 0
    with_flag = capsys.readouterr()

    assert with_flag.out == without_flag.out
    assert with_flag.err == without_flag.err == ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "banking.summary/v1"
    assert payload["status"] == "full_success"
    assert payload["exit_code"] == 0
    assert payload["raw_tab"] == "2026-11"
    assert payload["layout_tab"] == "2026-11 Gastos"
    assert payload["sheets_error"] is None


def test_summary_json_payload_matches_the_printed_headline_and_the_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The document repeats what the process printed, not a re-derived prose."""
    summary = _full_success_summary()
    monkeypatch.setattr(cli_daily, "run_daily", lambda: summary)
    _explode_on_notifier_build(monkeypatch)
    path = tmp_path / "summary.json"

    assert cli_daily.handle(_daily_args(path)) == 0
    out = capsys.readouterr().out

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["headline"] == out.splitlines()[0]
    assert payload["date"] == date.today().isoformat()
    assert payload["duration_seconds"] == summary.duration_seconds
    assert payload["banks_total"] == len(summary.passes) == 2
    assert payload["banks_succeeded"] == 2
    assert payload["banks_not_onboarded"] == 0
    assert payload["banks_failed"] == 0
    assert payload["balance_failures"] == 0
    assert payload["rows_written"] == summary.total_rows_written
    assert payload["expense_count"] == summary.expense_count
    assert payload["balance_count"] == summary.balance_count
    assert payload["not_onboarded_banks"] == []
    first, second = payload["banks"]
    assert first["bank"] == _BANK_A
    assert first["transactions"] == 2
    assert first["balance_reported"] is True
    assert first["not_onboarded"] is False
    assert second["bank"] == _BANK_B
    assert second["transactions"] == 1


def test_summary_json_records_the_nothing_to_sync_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run in which no bank is onboarded still writes the document."""
    monkeypatch.setattr(cli_daily, "run_daily", lambda: _not_onboarded_summary())
    _explode_on_notifier_build(monkeypatch)
    path = tmp_path / "summary.json"

    assert cli_daily.handle(_daily_args(path)) == 0

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "nothing_to_sync"
    assert payload["exit_code"] == 0
    assert payload["banks_not_onboarded"] == 2
    assert payload["not_onboarded_banks"] == [_BANK_A, _BANK_B]
    assert payload["rows_written"] == 0
    assert payload["headline"].startswith("Pasada diaria omitida")


@pytest.mark.parametrize(
    ("exc", "status", "delivery", "expected_exit"),
    [
        pytest.param(
            _total_failure_exception(), "total_failure", DeliveryStatus.SENT, 1, id="total"
        ),
        pytest.param(
            DailySheetsError("no access", stage="raw", tab_name="2026-11"),
            "sheets_failure",
            DeliveryStatus.SENT,
            2,
            id="sheets",
        ),
        pytest.param(
            _total_failure_exception(), "total_failure", DeliveryStatus.FAILED, 4, id="undelivered"
        ),
    ],
)
def test_summary_json_is_written_on_the_failure_paths_with_the_final_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
    exc: BaseException,
    status: str,
    delivery: DeliveryStatus,
    expected_exit: int,
) -> None:
    """Every terminal path writes the document, carrying the code the run exits with."""
    monkeypatch.setattr(cli_daily, "run_daily", _raise(exc))
    notifier = _mock_notifier(mocker, delivery)
    _install_notifier(monkeypatch, notifier)
    path = tmp_path / "summary.json"

    exit_code = cli_daily.handle(_daily_args(path))

    assert exit_code == expected_exit
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == status
    assert payload["exit_code"] == exit_code
    # The headline is the exact ERROR: line, so the workflow copies prose the
    # process authored even on the paths where it prints no summary line.
    assert payload["headline"] in capsys.readouterr().err
    assert payload["headline"].startswith("ERROR")


@pytest.mark.parametrize(
    ("stage", "tab_name", "raw_tab", "layout_tab"),
    [
        pytest.param("raw", "2026-11", "2026-11", "2026-11 Gastos", id="raw"),
        pytest.param("layout", "2026-11 Gastos", "2026-11", "2026-11 Gastos", id="layout"),
    ],
)
def test_summary_json_names_the_right_tab_for_the_failed_sheets_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    stage: str,
    tab_name: str,
    raw_tab: str,
    layout_tab: str,
) -> None:
    """Only the failed stage names its tab; the other keeps the month's own name."""
    exc = DailySheetsError(
        "no access",
        stage=stage,
        passes=[_pass(_BANK_A, transactions=(_transaction(),), balance=_balance())],
        tab_name=tab_name,
    )
    monkeypatch.setattr(cli_daily, "run_daily", _raise(exc))
    _install_notifier(monkeypatch, _mock_notifier(mocker))
    path = tmp_path / "summary.json"

    assert cli_daily.handle(_daily_args(path)) == 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "sheets_failure"
    assert payload["raw_tab"] == raw_tab
    assert payload["layout_tab"] == layout_tab


def test_summary_json_records_exit_four_when_the_notification_fails_on_a_partial_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mocker: MockerFixture,
) -> None:
    """A notification that blows up still writes the document with exit code 4."""
    monkeypatch.setattr(cli_daily, "run_daily", lambda: _partial_failure_summary())
    store = mocker.Mock()
    store.get.side_effect = RuntimeError("secret store unavailable")
    notifier = EmailNotifier(store=store, smtp_factory=mocker.Mock())
    _install_notifier(monkeypatch, notifier)
    path = tmp_path / "summary.json"

    exit_code = cli_daily.handle(_daily_args(path))

    assert exit_code == 4
    assert _NOTIFICATION_FAILED in capsys.readouterr().err
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "partial_failure"
    assert payload["exit_code"] == 4


def test_summary_json_write_failure_warns_once_and_keeps_the_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unwritable path degrades to one stderr warning, never to a new exit code."""
    monkeypatch.setattr(cli_daily, "run_daily", lambda: _full_success_summary())
    _explode_on_notifier_build(monkeypatch)
    path = tmp_path / "missing-directory" / "summary.json"

    assert cli_daily.handle(_daily_args(path)) == 0

    captured = capsys.readouterr()
    assert "Pasada diaria completada" in captured.out
    warnings = [line for line in captured.err.splitlines() if line.strip()]
    assert len(warnings) == 1, f"Expected one warning line, got {warnings}"
    assert "AVISO" in warnings[0]
    assert not path.exists()
