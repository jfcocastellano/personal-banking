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
from banking.daily import (
    BankPass,
    DailySheetsError,
    DailySummary,
    NoBankFetchedError,
    collect_bank_runs,
    run_daily,
)
from banking.sheets.layout import AccountBalance, ExpenseRow
from banking.sheets.writer import CellValue
from banking.sync import NoConnectorsError, OverallStatus

_START = date(2026, 11, 1)
_END = date(2026, 11, 20)
_DOCUMENT_ID = "doc-id"
_RAW_HEADERS: list[CellValue] = [
    "Fecha de liquidación",
    "Banco",
    "Descripción",
    "Importe",
    "Divisa",
    "Categoría",
]


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
        BankPass(
            bank_name="ING España",
            transactions=(_transaction("ING tx"),),
            balance=_balance("120.00"),
        ),
        BankPass(
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
        BankPass(
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
        BankPass(
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
        BankPass(
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
    assert runs == (BankPass(bank_name="Sabadell", not_onboarded=True),)

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
        BankPass(
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
        BankPass(
            bank_name="ING España",
            transactions=(),
            balance=None,
            transactions_failure="transactions exploded",
            balance_failure="balance exploded",
        ),
        BankPass(
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


# --- Clasificación, guardas y escritura de las dos pestañas (T002) ---------


class _RecordingWriter:
    """Offline stand-in for ``SheetsWriter``: records every write and can fail on demand."""

    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error
        self.calls: list[dict[str, object]] = []

    def write(
        self,
        document_id: str,
        tab_name: str,
        headers: list[CellValue],
        rows: list[list[CellValue]],
    ) -> None:
        self.calls.append(
            {"document_id": document_id, "tab_name": tab_name, "headers": headers, "rows": rows}
        )
        if self._error is not None:
            raise self._error


class _RecordingLayoutWriter:
    """Offline stand-in for ``LayoutWriter``: records every write and can fail on demand."""

    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error
        self.calls: list[dict[str, object]] = []

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
        if self._error is not None:
            raise self._error


class _ExplodingWriter:
    """Fails the test if the daily pass writes the raw tab when it must not."""

    def write(self, **kwargs: object) -> None:
        raise AssertionError(f"the raw tab must not be written: {kwargs}")


class _ExplodingLayoutWriter:
    """Fails the test if the daily pass writes the layout tab when it must not."""

    def write(self, **kwargs: object) -> None:
        raise AssertionError(f"the layout tab must not be written: {kwargs}")


class _ExplodingSecretStore:
    """Fails the test if the daily pass reads the spreadsheet secret."""

    def get(self, key: str) -> str:
        raise AssertionError(f"the secret store must not be read (key={key})")


def _row(description: str, amount: str = "10.00", bank: str = "ING España") -> list[CellValue]:
    return ["2026-11-05", bank, description, float(Decimal(amount)), "EUR", ""]


def _expense(description: str, amount: str, bank: str) -> ExpenseRow:
    return ExpenseRow(
        booking_date=date(2026, 11, 5),
        bank=bank,
        description=description,
        amount=Decimal(amount),
        category="",
    )


def test_run_daily_full_success_writes_both_tabs_with_the_same_movements() -> None:
    ing = _FakeConnector(
        "ING España",
        transactions=[_transaction("ING tx"), _transaction("ING tx 2", "-3.00")],
        balance=_balance("120.00"),
    )
    revolut = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx", "-5.00")],
        balance=_balance("80.00"),
    )
    raw_writer = _RecordingWriter()
    layout_writer = _RecordingLayoutWriter()

    summary = run_daily(
        connectors=[ing, revolut],
        writer=raw_writer,
        layout_writer=layout_writer,
        document_id=_DOCUMENT_ID,
        today=_END,
    )

    # Range: first day of the month .. execution date, one query per stage.
    for connector in (ing, revolut):
        assert connector.transactions_calls == [(_START, _END)]
        assert connector.balance_calls == 1

    assert raw_writer.calls == [
        {
            "document_id": _DOCUMENT_ID,
            "tab_name": "2026-11",
            "headers": _RAW_HEADERS,
            "rows": [
                _row("ING tx"),
                _row("ING tx 2", "-3.00"),
                _row("Revolut tx", "-5.00", bank="Revolut"),
            ],
        }
    ]
    assert layout_writer.calls == [
        {
            "document_id": _DOCUMENT_ID,
            "tab_name": "2026-11 Gastos",
            "transactions": [
                _expense("ING tx", "10.00", "ING España"),
                _expense("ING tx 2", "-3.00", "ING España"),
                _expense("Revolut tx", "-5.00", "Revolut"),
            ],
            "balances": [
                AccountBalance(
                    bank="ING España",
                    amount=Decimal("120.00"),
                    reference_date=date(2026, 11, 20),
                ),
                AccountBalance(
                    bank="Revolut",
                    amount=Decimal("80.00"),
                    reference_date=date(2026, 11, 20),
                ),
            ],
        }
    ]

    # FR-002: both tabs carry the same movement set, counted as rows.
    assert len(layout_writer.calls[0]["transactions"]) == len(raw_writer.calls[0]["rows"])
    assert summary == DailySummary(
        passes=[
            BankPass(
                bank_name="ING España",
                transactions=(_transaction("ING tx"), _transaction("ING tx 2", "-3.00")),
                balance=_balance("120.00"),
            ),
            BankPass(
                bank_name="Revolut",
                transactions=(_transaction("Revolut tx", "-5.00"),),
                balance=_balance("80.00"),
            ),
        ],
        overall_status=OverallStatus.FULL_SUCCESS,
        raw_tab_name="2026-11",
        layout_tab_name="2026-11 Gastos",
        total_rows_written=3,
        expense_count=3,
        balance_count=2,
        duration_seconds=summary.duration_seconds,
    )
    assert summary.duration_seconds >= 0


def test_run_daily_bank_with_zero_movements_still_counts_as_success() -> None:
    empty = _FakeConnector("Revolut", balance=_balance("80.00"))
    healthy = _FakeConnector(
        "ING España",
        transactions=[_transaction("ING tx")],
        balance=_balance("120.00"),
    )
    raw_writer = _RecordingWriter()
    layout_writer = _RecordingLayoutWriter()

    summary = run_daily(
        connectors=[empty, healthy],
        writer=raw_writer,
        layout_writer=layout_writer,
        document_id=_DOCUMENT_ID,
        today=_END,
    )

    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    assert summary.total_rows_written == 1
    assert summary.balance_count == 2
    assert len(layout_writer.calls) == 1
    assert len(raw_writer.calls) == 1


def test_run_daily_all_not_onboarded_writes_nothing_and_never_reads_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = [
        _FakeConnector(
            "ING España",
            transactions_error=BankNotOnboardedError("no PSD2 session configured"),
            balance_error=BankNotOnboardedError("no PSD2 session configured"),
        ),
        _FakeConnector(
            "Revolut",
            transactions_error=BankNotOnboardedError("no PSD2 session configured"),
        ),
    ]
    monkeypatch.setattr("banking.daily.SecretStore", _ExplodingSecretStore)

    with caplog.at_level(logging.INFO, logger="banking.daily"):
        summary = run_daily(
            connectors=connectors,
            writer=_ExplodingWriter(),
            layout_writer=_ExplodingLayoutWriter(),
            today=_END,
        )

    assert summary.overall_status == OverallStatus.NOTHING_TO_SYNC
    assert summary.total_rows_written == 0
    assert summary.expense_count == 0
    assert summary.balance_count == 0
    assert summary.raw_tab_name == "2026-11"
    assert summary.layout_tab_name == "2026-11 Gastos"
    assert {run.not_onboarded for run in summary.passes} == {True}

    records = _daily_records(caplog)
    assert records
    assert {record.levelno for record in records} == {logging.INFO}


def test_run_daily_total_failure_raises_without_writing_anything(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = [
        _FakeConnector(
            "ING España",
            transactions_error=RuntimeError("ing boom"),
            balance_error=RuntimeError("ing boom"),
        ),
        _FakeConnector(
            "Revolut",
            transactions_error=RuntimeError("revolut boom"),
            balance_error=RuntimeError("revolut boom"),
        ),
    ]
    monkeypatch.setattr("banking.daily.SecretStore", _ExplodingSecretStore)

    with caplog.at_level(logging.ERROR, logger="banking.daily"):
        with pytest.raises(NoBankFetchedError) as excinfo:
            run_daily(
                connectors=connectors,
                writer=_ExplodingWriter(),
                layout_writer=_ExplodingLayoutWriter(),
                today=_END,
            )

    exc = excinfo.value
    assert [run.bank_name for run in exc.passes] == ["ING España", "Revolut"]
    assert exc.raw_tab_name == "2026-11"
    assert exc.layout_tab_name == "2026-11 Gastos"
    assert "ING España: ing boom" in str(exc)

    errors = [record for record in _daily_records(caplog) if record.levelno == logging.ERROR]
    assert errors
    assert all("not onboarded" not in record.getMessage().lower() for record in errors)


def test_run_daily_total_failure_message_never_calls_not_onboarded_banks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connectors = [
        _FakeConnector(
            "ING España",
            transactions_error=RuntimeError("ing boom"),
            balance_error=RuntimeError("ing boom"),
        ),
        _FakeConnector(
            "Sabadell",
            transactions_error=BankNotOnboardedError("no PSD2 session configured"),
        ),
    ]
    monkeypatch.setattr("banking.daily.SecretStore", _ExplodingSecretStore)

    with pytest.raises(NoBankFetchedError) as excinfo:
        run_daily(
            connectors=connectors,
            writer=_ExplodingWriter(),
            layout_writer=_ExplodingLayoutWriter(),
            today=_END,
        )

    message = str(excinfo.value)
    assert "Failed: ING España: ing boom" in message
    assert "Sabadell" in message
    assert "Sabadell: " not in message


def test_run_daily_one_success_and_one_failure_is_partial_and_writes_both_tabs() -> None:
    failing = _FakeConnector(
        "ING España",
        transactions_error=RuntimeError("ing boom"),
        balance_error=RuntimeError("ing boom"),
    )
    healthy = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx")],
        balance=_balance("80.00"),
    )
    raw_writer = _RecordingWriter()
    layout_writer = _RecordingLayoutWriter()

    summary = run_daily(
        connectors=[failing, healthy],
        writer=raw_writer,
        layout_writer=layout_writer,
        document_id=_DOCUMENT_ID,
        today=_END,
    )

    assert summary.overall_status == OverallStatus.PARTIAL_FAILURE
    assert summary.total_rows_written == 1
    assert summary.expense_count == 1
    assert summary.balance_count == 2
    assert len(raw_writer.calls) == 1
    assert len(layout_writer.calls) == 1


def test_run_daily_raw_failure_raises_before_the_layout_writer_is_called() -> None:
    connector = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx")],
        balance=_balance("80.00"),
    )
    layout_writer = _RecordingLayoutWriter()

    with pytest.raises(DailySheetsError) as excinfo:
        run_daily(
            connectors=[connector],
            writer=_RecordingWriter(error=RuntimeError("raw exploded")),
            layout_writer=layout_writer,
            document_id=_DOCUMENT_ID,
            today=_END,
        )

    exc = excinfo.value
    assert exc.stage == "raw"
    assert exc.tab_name == "2026-11"
    assert str(exc) == "raw exploded"
    assert [run.bank_name for run in exc.passes] == ["Revolut"]
    assert layout_writer.calls == []


def test_run_daily_layout_failure_raises_after_the_raw_tab_was_written() -> None:
    connector = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx")],
        balance=_balance("80.00"),
    )
    raw_writer = _RecordingWriter()
    layout_writer = _RecordingLayoutWriter(error=RuntimeError("layout exploded"))

    with pytest.raises(DailySheetsError) as excinfo:
        run_daily(
            connectors=[connector],
            writer=raw_writer,
            layout_writer=layout_writer,
            document_id=_DOCUMENT_ID,
            today=_END,
        )

    exc = excinfo.value
    assert exc.stage == "layout"
    assert exc.tab_name == "2026-11 Gastos"
    assert str(exc) == "layout exploded"
    assert [run.bank_name for run in exc.passes] == ["Revolut"]
    assert len(raw_writer.calls) == 1
    assert len(layout_writer.calls) == 1


def test_run_daily_balance_failure_keeps_movements_and_writes_an_empty_balance_row() -> None:
    connector = _FakeConnector(
        "Revolut",
        transactions=[_transaction("Revolut tx")],
        balance_error=RuntimeError("balance exploded"),
    )
    raw_writer = _RecordingWriter()
    layout_writer = _RecordingLayoutWriter()

    summary = run_daily(
        connectors=[connector],
        writer=raw_writer,
        layout_writer=layout_writer,
        document_id=_DOCUMENT_ID,
        today=_END,
    )

    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    assert summary.total_rows_written == 1
    assert summary.expense_count == 1
    assert summary.balance_count == 1
    assert raw_writer.calls[0]["rows"] == [_row("Revolut tx", bank="Revolut")]
    assert layout_writer.calls[0]["balances"] == [
        AccountBalance(bank="Revolut", amount=None, currency="EUR", reference_date=None)
    ]


def test_run_daily_without_connectors_raises_no_connectors_error() -> None:
    with pytest.raises(NoConnectorsError):
        run_daily(
            connectors=[],
            writer=_ExplodingWriter(),
            layout_writer=_ExplodingLayoutWriter(),
            document_id=_DOCUMENT_ID,
            today=_END,
        )


def test_success_log_separates_balance_rows_from_reported_balances(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bank without a balance still gets a row; the log must not call it a balance."""
    reporting = _FakeConnector(
        "ING España",
        transactions=[_transaction("ING tx")],
        balance=_balance("120.00"),
    )
    silent = _FakeConnector(
        "MyInvestor",
        transactions_error=BankNotOnboardedError("no PSD2 session configured"),
    )

    with caplog.at_level(logging.INFO, logger="banking.daily"):
        run_daily(
            connectors=[reporting, silent],
            writer=_RecordingWriter(),
            layout_writer=_RecordingLayoutWriter(),
            document_id=_DOCUMENT_ID,
            today=_END,
        )

    succeeded = [
        record.getMessage()
        for record in _daily_records(caplog)
        if "Daily pass succeeded" in record.getMessage()
    ]
    assert len(succeeded) == 1
    assert "balance_rows=2" in succeeded[0]
    assert "balances_reported=1" in succeeded[0]


# --- T2: la pestaña cruda se lee del movimiento más viejo al más nuevo ------


def _transaction_on(booking_date: date, description: str, amount: str) -> Transaction:
    return Transaction(
        booking_date=booking_date,
        amount=Decimal(amount),
        currency="EUR",
        description=description,
    )


def test_run_daily_writes_the_raw_tab_oldest_first_across_banks() -> None:
    """The daily call path flattens banks in one ascending order, not bank by bank."""
    ing = _FakeConnector(
        "ING España",
        transactions=[
            _transaction_on(date(2026, 11, 9), "ING última", "10.00"),
            _transaction_on(date(2026, 11, 5), "ING primera", "10.00"),
        ],
        balance=_balance("120.00"),
    )
    revolut = _FakeConnector(
        "Revolut",
        transactions=[
            _transaction_on(date(2026, 11, 5), "Revolut mismo día", "-5.00"),
            _transaction_on(date(2026, 11, 2), "Revolut primera", "-1.00"),
        ],
        balance=_balance("80.00"),
    )
    raw_writer = _RecordingWriter()

    run_daily(
        connectors=[ing, revolut],
        writer=raw_writer,
        layout_writer=_RecordingLayoutWriter(),
        document_id=_DOCUMENT_ID,
        today=_END,
    )

    raw_rows = raw_writer.calls[0]["rows"]
    assert [(row[0], row[1], row[2]) for row in raw_rows] == [
        ("2026-11-02", "Revolut", "Revolut primera"),
        ("2026-11-05", "ING España", "ING primera"),
        ("2026-11-05", "Revolut", "Revolut mismo día"),
        ("2026-11-09", "ING España", "ING última"),
    ]
