"""Tests for the single daily pass domain layer (banking.daily)."""

import logging
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from banking.connectors.enable_banking import (
    Balance,
    BankNotOnboardedError,
    Transaction,
)
from banking.daily import BankRun, collect_bank_runs

_START = date(2026, 11, 1)
_END = date(2026, 11, 20)


class _FakeConnector:
    """Offline stand-in for a bank connector that records every call it receives.

    Never touches the network or ``SecretStore``: the tests need only the two
    call counts and the configured answers.
    """

    def __init__(
        self,
        bank_name: str,
        *,
        transactions: Sequence[Transaction] = (),
        balance: Balance | None = None,
        transactions_error: BaseException | None = None,
        balance_error: BaseException | None = None,
    ) -> None:
        self.BANK_NAME = bank_name
        self._transactions = list(transactions)
        self._balance = balance
        self._transactions_error = transactions_error
        self._balance_error = balance_error
        self.transactions_calls: list[tuple[date, date]] = []
        self.balance_calls = 0

    def fetch_transactions(self, start_date: date, end_date: date) -> list[Transaction]:
        self.transactions_calls.append((start_date, end_date))
        if self._transactions_error is not None:
            raise self._transactions_error
        return list(self._transactions)

    def fetch_balance(self) -> Balance | None:
        self.balance_calls += 1
        if self._balance_error is not None:
            raise self._balance_error
        return self._balance


def _transaction(description: str, amount: str = "10.00") -> Transaction:
    return Transaction(
        booking_date=date(2026, 11, 5),
        amount=Decimal(amount),
        currency="EUR",
        description=description,
    )


def _balance(amount: str = "100.00") -> Balance:
    return Balance(
        amount=Decimal(amount),
        currency="EUR",
        balance_type="CLBD",
        reference_date=date(2026, 11, 20),
    )


def _daily_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "banking.daily"]


# --- Una sola consulta por banco y por etapa -------------------------------


def test_collect_bank_runs_queries_each_bank_once_per_stage() -> None:
    ing = _FakeConnector(
        "ING España",
        transactions=[_transaction("ING tx")],
        balance=_balance("120.00"),
    )
    revolut = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx", "-5.00"), _transaction("Revolut tx 2")],
        balance=_balance("80.00"),
    )

    runs = collect_bank_runs([ing, revolut], start_date=_START, end_date=_END)

    for connector in (ing, revolut):
        assert connector.transactions_calls == [(_START, _END)]
        assert connector.balance_calls == 1
    assert runs == (
        BankRun(
            bank_name="ING España",
            transactions=(_transaction("ING tx"),),
            balance=_balance("120.00"),
        ),
        BankRun(
            bank_name="Revolut",
            transactions=(
                _transaction("Revolut tx", "-5.00"),
                _transaction("Revolut tx 2"),
            ),
            balance=_balance("80.00"),
        ),
    )


def test_collect_bank_runs_preserves_input_order() -> None:
    connectors = [
        _FakeConnector("Banco Sabadell"),
        _FakeConnector("ING España"),
        _FakeConnector("MyInvestor"),
        _FakeConnector("Revolut"),
    ]

    runs = collect_bank_runs(connectors, start_date=_START, end_date=_END)

    assert [run.bank_name for run in runs] == [
        "Banco Sabadell",
        "ING España",
        "MyInvestor",
        "Revolut",
    ]


# --- Aislamiento por etapa -------------------------------------------------


def test_transactions_failure_keeps_balance() -> None:
    connector = _FakeConnector(
        "ING España",
        transactions_error=RuntimeError("transactions exploded"),
        balance=_balance("120.00"),
    )

    runs = collect_bank_runs([connector], start_date=_START, end_date=_END)

    assert connector.balance_calls == 1
    assert runs == (
        BankRun(
            bank_name="ING España",
            transactions=(),
            balance=_balance("120.00"),
            transactions_failure="transactions exploded",
        ),
    )


def test_balance_failure_keeps_transactions() -> None:
    connector = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx")],
        balance_error=RuntimeError("balance exploded"),
    )

    runs = collect_bank_runs([connector], start_date=_START, end_date=_END)

    assert runs == (
        BankRun(
            bank_name="Revolut",
            transactions=(_transaction("Revolut tx"),),
            balance=None,
            balance_failure="balance exploded",
        ),
    )


def test_balance_returning_none_is_not_a_failure() -> None:
    connector = _FakeConnector("MyInvestor", transactions=[_transaction("MyInvestor tx")])

    runs = collect_bank_runs([connector], start_date=_START, end_date=_END)

    assert runs == (
        BankRun(
            bank_name="MyInvestor",
            transactions=(_transaction("MyInvestor tx"),),
            balance=None,
        ),
    )
    assert runs[0].balance_failure is None


# --- Bancos sin sesión PSD2: INFO, nunca ERROR -----------------------------


def test_not_onboarded_in_transactions_marks_bank_and_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _FakeConnector(
        "Sabadell",
        transactions_error=BankNotOnboardedError("no PSD2 session configured"),
    )

    with caplog.at_level(logging.INFO, logger="banking.daily"):
        runs = collect_bank_runs([connector], start_date=_START, end_date=_END)

    assert connector.balance_calls == 1
    assert runs == (BankRun(bank_name="Sabadell", not_onboarded=True),)

    records = _daily_records(caplog)
    assert records
    assert {record.levelno for record in records} == {logging.INFO}
    assert all("Sabadell" in record.getMessage() for record in records)


def test_not_onboarded_in_balance_marks_bank_and_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _FakeConnector(
        "Sabadell",
        transactions=[_transaction("Sabadell tx")],
        balance_error=BankNotOnboardedError("no PSD2 session configured"),
    )

    with caplog.at_level(logging.INFO, logger="banking.daily"):
        runs = collect_bank_runs([connector], start_date=_START, end_date=_END)

    assert runs == (
        BankRun(
            bank_name="Sabadell",
            transactions=(_transaction("Sabadell tx"),),
            not_onboarded=True,
        ),
    )

    records = _daily_records(caplog)
    assert records
    assert {record.levelno for record in records} == {logging.INFO}
    assert all("Sabadell" in record.getMessage() for record in records)


# --- Un fallo real no aborta la corrida ------------------------------------


def test_generic_failure_is_captured_and_other_banks_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failing = _FakeConnector(
        "ING España",
        transactions_error=RuntimeError("transactions exploded"),
        balance_error=RuntimeError("balance exploded"),
    )
    healthy = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx")],
        balance=_balance("80.00"),
    )

    with caplog.at_level(logging.INFO, logger="banking.daily"):
        runs = collect_bank_runs([failing, healthy], start_date=_START, end_date=_END)

    assert runs == (
        BankRun(
            bank_name="ING España",
            transactions=(),
            balance=None,
            transactions_failure="transactions exploded",
            balance_failure="balance exploded",
        ),
        BankRun(
            bank_name="Revolut",
            transactions=(_transaction("Revolut tx"),),
            balance=_balance("80.00"),
        ),
    )

    errors = [record for record in _daily_records(caplog) if record.levelno == logging.ERROR]
    assert len(errors) == 2
    messages = " ".join(record.getMessage() for record in errors)
    assert "ING España" in messages
    assert "transactions" in messages
    assert "balance" in messages
