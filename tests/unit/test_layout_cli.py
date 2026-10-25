"""Tests for the `banking layout` CLI subcommand (no network, no spreadsheet).

The connector classes and ``LayoutWriter`` are always patched: a test that
reached a real bank API or a real Google Sheet would be a bug in this file.
"""

import argparse
import subprocess
import sys
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from banking.__main__ import _build_parser
from banking.cli import layout as layout_cli
from banking.connectors.enable_banking import Balance, Transaction
from banking.sheets.layout import AccountBalance, ExpenseRow
from banking.sheets.writer import SheetsAccessError

_BANK_A = "ING España"
_BANK_B = "Revolut"


class _FakeSecretStore:
    """Stands in for SecretStore so no encrypted configuration is read."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def get(self, key: str) -> str:
        return "fake-document-id"


class RecordingWriter:
    """Records every LayoutWriter.write call and can be made to fail."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def write(
        self,
        document_id: str,
        tab_name: str,
        transactions: Sequence[ExpenseRow],
        balances: Sequence[AccountBalance],
    ) -> None:
        self.calls.append(
            {
                "document_id": document_id,
                "tab_name": tab_name,
                "transactions": list(transactions),
                "balances": list(balances),
            }
        )
        if self.error is not None:
            raise self.error


def _transaction(day: int, amount: str = "-10.00", description: str = "Compra") -> Transaction:
    return Transaction(
        booking_date=date(2026, 8, day),
        amount=Decimal(amount),
        currency="EUR",
        description=description,
    )


def _balance(amount: str = "1234.50") -> Balance:
    return Balance(
        amount=Decimal(amount),
        currency="EUR",
        balance_type="CLBD",
        reference_date=date(2026, 8, 31),
    )


def _connector_class(
    bank_name: str,
    *,
    transactions: list[Transaction] | None = None,
    transactions_error: Exception | None = None,
    balance: Balance | None = None,
    balance_error: Exception | None = None,
    calls: list[tuple[date, date]] | None = None,
) -> type:
    """Build a fake connector class with the injected behaviour."""

    class _FakeConnector:
        BANK_NAME = bank_name

        def __init__(self) -> None:
            pass

        def fetch_transactions(self, start_date: date, end_date: date) -> list[Transaction]:
            if calls is not None:
                calls.append((start_date, end_date))
            if transactions_error is not None:
                raise transactions_error
            return list(transactions or [])

        def fetch_balance(self) -> Balance | None:
            if balance_error is not None:
                raise balance_error
            return balance

    return _FakeConnector


def _install(
    monkeypatch: pytest.MonkeyPatch,
    connectors: list[type],
    writer: RecordingWriter,
) -> RecordingWriter:
    monkeypatch.setattr(layout_cli, "_CONNECTOR_CLASSES", tuple(connectors))
    monkeypatch.setattr(layout_cli, "LayoutWriter", lambda: writer)
    monkeypatch.setattr(layout_cli, "SecretStore", _FakeSecretStore)
    return writer


def _run(month: object, monkeypatch: pytest.MonkeyPatch, writer: RecordingWriter) -> int:
    monkeypatch.setattr(layout_cli, "LayoutWriter", lambda: writer)
    monkeypatch.setattr(layout_cli, "SecretStore", _FakeSecretStore)
    return layout_cli.handle(argparse.Namespace(month=month))


# --- registration -----------------------------------------------------------


def test_layout_subcommand_is_registered() -> None:
    args = _build_parser().parse_args(["layout"])

    assert args.command == "layout"
    assert args.month is None


def test_layout_subcommand_accepts_a_month_and_defaults_its_help() -> None:
    args = _build_parser().parse_args(["layout", "--month", "2026-08"])

    assert args.month == date(2026, 8, 1)


def test_layout_appears_in_the_usage_listing() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "banking"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "layout" in result.stdout
    assert "secrets" in result.stdout
    assert "sync" in result.stdout


def test_layout_help_documents_the_month_option() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "banking", "layout", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--month" in result.stdout
    assert "YYYY-MM" in result.stdout


# --- month validation -------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("2026-8", id="single-digit-month"),
        pytest.param("2026-13", id="month-13"),
        pytest.param("2026-00", id="month-zero"),
        pytest.param("202608", id="no-separator"),
        pytest.param("2026-08-01", id="full-date"),
        pytest.param("abc", id="garbage"),
        pytest.param("", id="empty"),
    ],
)
def test_malformed_month_is_rejected_by_the_parser_with_exit_two(
    raw: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["layout", "--month", raw])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower()
    assert "YYYY-MM" in captured.err


def test_malformed_month_exits_two_without_touching_the_writer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = RecordingWriter()

    exit_code = _run("2026-13", monkeypatch, writer)

    assert exit_code == 2
    assert writer.calls == []
    captured = capsys.readouterr()
    assert "2026-13" in captured.err
    assert "YYYY-MM" in captured.err
    assert "mes no válido" in captured.err


# --- successful run ---------------------------------------------------------


def test_successful_run_writes_the_gastos_tab_and_never_the_plain_month_tab(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [_connector_class(_BANK_A, transactions=[_transaction(3)], balance=_balance("111.00"))],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    assert len(writer.calls) == 1
    assert writer.calls[0]["tab_name"] == "2026-08 Gastos"
    assert writer.calls[0]["tab_name"] != "2026-08"
    assert "2026-08 Gastos" in capsys.readouterr().out


def test_month_defaults_to_the_current_month(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[date, date]] = []
    writer = _install(
        monkeypatch,
        [_connector_class(_BANK_A, transactions=[_transaction(1)], calls=calls)],
        RecordingWriter(),
    )

    exit_code = _run(None, monkeypatch, writer)

    today = date.today()
    assert exit_code == 0
    assert writer.calls[0]["tab_name"] == f"{today.strftime('%Y-%m')} Gastos"
    assert calls == [(today.replace(day=1), today)]


@pytest.mark.parametrize(
    ("month", "today", "expected"),
    [
        pytest.param(date(2026, 8, 1), date(2026, 8, 15), (date(2026, 8, 1), date(2026, 8, 15))),
        pytest.param(date(2026, 8, 1), date(2026, 8, 31), (date(2026, 8, 1), date(2026, 8, 31))),
        pytest.param(date(2026, 2, 1), date(2026, 8, 15), (date(2026, 2, 1), date(2026, 2, 28))),
        pytest.param(date(2026, 1, 1), date(2026, 8, 15), (date(2026, 1, 1), date(2026, 1, 31))),
    ],
)
def test_month_range_is_the_month_capped_at_today(
    month: date, today: date, expected: tuple[date, date]
) -> None:
    assert layout_cli._month_range(month, today) == expected


def test_run_layout_fetches_the_whole_requested_month(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[date, date]] = []
    writer = _install(
        monkeypatch,
        [_connector_class(_BANK_A, transactions=[_transaction(1)], calls=calls)],
        RecordingWriter(),
    )

    layout_cli.run_layout(month=date(2026, 2, 1), today=date(2026, 8, 15))

    assert calls == [(date(2026, 2, 1), date(2026, 2, 28))]
    assert writer.calls[0]["tab_name"] == "2026-02 Gastos"


def test_transactions_become_expense_rows_with_the_bank_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(_BANK_A, transactions=[_transaction(3, "-9.50", "Café")]),
            _connector_class(_BANK_B, transactions=[_transaction(4, "1500.00", "Nómina")]),
        ],
        RecordingWriter(),
    )

    layout_cli.run_layout(month=date(2026, 8, 1), today=date(2026, 8, 31))

    rows = writer.calls[0]["transactions"]
    assert [(row.bank, row.description, row.amount) for row in rows] == [
        (_BANK_A, "Café", Decimal("-9.50")),
        (_BANK_B, "Nómina", Decimal("1500.00")),
    ]


# --- failure isolation ------------------------------------------------------


def test_transaction_failure_is_reported_yet_the_balance_still_contributes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(
                _BANK_A,
                transactions_error=RuntimeError("ing boom"),
                balance=_balance("500.00"),
            ),
            _connector_class(_BANK_B, transactions=[_transaction(4)], balance=_balance("42.00")),
        ],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    balances = writer.calls[0]["balances"]
    assert [balance.bank for balance in balances] == [_BANK_A, _BANK_B]
    assert balances[0].amount == Decimal("500.00")
    assert [row.bank for row in writer.calls[0]["transactions"]] == [_BANK_B]
    out = capsys.readouterr().out
    assert _BANK_A in out
    assert "ing boom" in out
    assert "FALLÓ" in out


def test_balance_failure_is_reported_yet_the_transactions_still_contribute(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(
                _BANK_A,
                transactions=[_transaction(3)],
                balance_error=RuntimeError("quota exceeded"),
            ),
            _connector_class(_BANK_B, transactions=[_transaction(4)], balance=_balance("42.00")),
        ],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    balances = writer.calls[0]["balances"]
    assert balances[0].bank == _BANK_A
    assert balances[0].amount is None  # no zero is invented
    assert [row.bank for row in writer.calls[0]["transactions"]] == [_BANK_A, _BANK_B]
    out = capsys.readouterr().out
    assert _BANK_A in out
    assert "quota exceeded" in out


def test_a_bank_reporting_no_balance_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [_connector_class(_BANK_A, transactions=[_transaction(3)], balance=None)],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    assert writer.calls[0]["balances"][0].amount is None
    out = capsys.readouterr().out
    assert "sin saldo informado" in out
    assert "FALLÓ" not in out


def test_one_bank_failing_everything_never_aborts_the_other_banks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(
                _BANK_A,
                transactions_error=RuntimeError("re-auth needed"),
                balance_error=RuntimeError("re-auth needed"),
            ),
            _connector_class(_BANK_B, transactions=[_transaction(4)], balance=_balance("42.00")),
        ],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    assert [row.bank for row in writer.calls[0]["transactions"]] == [_BANK_B]
    out = capsys.readouterr().out
    assert out.count("FALLÓ") == 2  # transactions and balance reported separately
    assert _BANK_B in out


def test_no_bank_able_to_fetch_transactions_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(
                _BANK_A, transactions_error=RuntimeError("a boom"), balance=_balance()
            ),
            _connector_class(
                _BANK_B, transactions_error=RuntimeError("b boom"), balance=_balance()
            ),
        ],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 3
    assert writer.calls == []
    captured = capsys.readouterr()
    assert "no se ha escrito la pestaña" in captured.err
    assert "a boom" in captured.out
    assert "b boom" in captured.out


def test_a_month_without_movements_still_writes_the_layout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bank succeeding with zero transactions is not a failure (spec edge case)."""
    writer = _install(
        monkeypatch,
        [_connector_class(_BANK_A, transactions=[], balance=_balance())],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    assert writer.calls[0]["transactions"] == []
    assert "0 movimientos" in capsys.readouterr().out


# --- write outcome ----------------------------------------------------------


def test_writer_failure_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = RecordingWriter(error=SheetsAccessError("doc-1 not found"))
    _install(
        monkeypatch,
        [_connector_class(_BANK_A, transactions=[_transaction(3)], balance=_balance())],
        writer,
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 1
    assert len(writer.calls) == 1
    captured = capsys.readouterr()
    assert "ERROR (layout)" in captured.err
    assert "2026-08 Gastos" in captured.err
    assert "doc-1 not found" in captured.err


def test_report_counts_match_what_was_passed_to_the_writer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(
                _BANK_A,
                transactions=[_transaction(3), _transaction(5)],
                balance=_balance(),
            ),
            _connector_class(_BANK_B, transactions=[_transaction(9)], balance=_balance("1.00")),
        ],
        RecordingWriter(),
    )

    exit_code = _run(date(2026, 8, 1), monkeypatch, writer)

    assert exit_code == 0
    written = writer.calls[0]
    assert len(written["transactions"]) == 3
    assert len(written["balances"]) == 2
    out = capsys.readouterr().out
    assert "Layout completado" in out
    assert f"{len(written['transactions'])} movimientos" in out
    assert f"{len(written['balances'])} saldos" in out
    assert "2026-08 Gastos" in out


def test_report_line_per_bank_in_the_configured_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = _install(
        monkeypatch,
        [
            _connector_class(_BANK_A, transactions=[_transaction(3)], balance=_balance()),
            _connector_class(_BANK_B, transactions=[_transaction(4)], balance=_balance()),
        ],
        RecordingWriter(),
    )

    _run(date(2026, 8, 1), monkeypatch, writer)

    out = capsys.readouterr().out
    assert out.index(_BANK_A) < out.index(_BANK_B)
