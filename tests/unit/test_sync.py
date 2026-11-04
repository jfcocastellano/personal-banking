"""Tests for the multi-bank sync pipeline (banking.sync)."""

import logging
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest

from banking.connectors.enable_banking import (
    BankNotOnboardedError,
    ConnectorConfigError,
    EnableBankingAPIError,
    EnableBankingConnector,
    PaginationLimitExceededError,
    RateLimitExceededError,
    ReauthorizationRequiredError,
    Transaction,
)
from banking.connectors.ing import IngConnector
from banking.connectors.myinvestor import MyInvestorConnector
from banking.connectors.revolut import RevolutConnector
from banking.connectors.sabadell import SabadellConnector
from banking.sheets.writer import (
    SheetsAccessError,
    SheetsAPIError,
    SheetsConfigError,
    SheetsQuotaExceededError,
    SheetsWriter,
)
from banking.sync import (
    AllBanksFailedError,
    BankOutcome,
    NoConnectorsError,
    OverallStatus,
    SheetsSyncError,
    run_sync,
)

_HEADERS = ["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"]


def _mock_connector(spec: type, transactions: list[Transaction]) -> Mock:
    connector = Mock(spec=spec)
    connector.BANK_NAME = spec.BANK_NAME
    connector.fetch_transactions.return_value = transactions
    return connector


def _four_connectors(
    ing_txs: list[Transaction] | None = None,
    revolut_txs: list[Transaction] | None = None,
    myinvestor_txs: list[Transaction] | None = None,
    sabadell_txs: list[Transaction] | None = None,
) -> list[Mock]:
    return [
        _mock_connector(IngConnector, ing_txs if ing_txs is not None else []),
        _mock_connector(RevolutConnector, revolut_txs if revolut_txs is not None else []),
        _mock_connector(MyInvestorConnector, myinvestor_txs if myinvestor_txs is not None else []),
        _mock_connector(SabadellConnector, sabadell_txs if sabadell_txs is not None else []),
    ]


# --- US1: sincronizar los cuatro bancos en una sola ejecución ---------------


def test_run_sync_all_four_succeed_combines_and_writes() -> None:
    ing_txs = [Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    revolut_txs = [Transaction(date(2026, 8, 2), Decimal("-5.00"), "EUR", "Revolut tx")]
    myinvestor_txs = [Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")]
    sabadell_txs = [Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")]
    connectors = _four_connectors(ing_txs, revolut_txs, myinvestor_txs, sabadell_txs)
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    for connector in connectors:
        connector.fetch_transactions.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 15))

    writer.write.assert_called_once_with(
        document_id="doc-id",
        tab_name="2026-08",
        headers=_HEADERS,
        rows=[
            ["2026-08-01", "ING España", "ING tx", 10.0, "EUR"],
            ["2026-08-02", "Revolut", "Revolut tx", -5.0, "EUR"],
            ["2026-08-03", "MyInvestor", "MyInvestor tx", 20.0, "EUR"],
            ["2026-08-04", "Banco Sabadell", "Sabadell tx", -2.5, "EUR"],
        ],
    )
    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    assert summary.tab_name == "2026-08"
    assert summary.total_rows_written == 4
    assert summary.outcomes == [
        BankOutcome(bank_name="ING España", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(bank_name="Revolut", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(bank_name="MyInvestor", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(
            bank_name="Banco Sabadell", succeeded=True, rows_written=1, failure_reason=None
        ),
    ]


def test_run_sync_bank_with_no_transactions_still_counts_as_success() -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        revolut_txs=[],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    revolut_outcome = next(o for o in summary.outcomes if o.bank_name == "Revolut")
    assert revolut_outcome == BankOutcome(
        bank_name="Revolut", succeeded=True, rows_written=0, failure_reason=None
    )
    written_rows = writer.write.call_args.kwargs["rows"]
    assert all(row[1] != "Revolut" for row in written_rows)
    assert len(written_rows) == 3


# --- US2: continuar cuando un banco falla, sin perder los datos de los demás -


@pytest.mark.parametrize(
    "exc_type",
    [
        ReauthorizationRequiredError,
        RateLimitExceededError,
        EnableBankingAPIError,
        ConnectorConfigError,
        PaginationLimitExceededError,
        httpx.TimeoutException,
    ],
)
def test_run_sync_one_bank_fails_others_continue(exc_type: type[Exception]) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    connectors[1].fetch_transactions.side_effect = exc_type("boom")  # Revolut falla
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    for connector in connectors:
        connector.fetch_transactions.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 15))

    assert summary.overall_status == OverallStatus.PARTIAL_FAILURE
    revolut_outcome = next(o for o in summary.outcomes if o.bank_name == "Revolut")
    assert revolut_outcome.succeeded is False
    assert revolut_outcome.rows_written is None
    assert "boom" in (revolut_outcome.failure_reason or "")
    other_outcomes = [o for o in summary.outcomes if o.bank_name != "Revolut"]
    assert all(o.succeeded for o in other_outcomes)

    writer.write.assert_called_once()
    written_rows = writer.write.call_args.kwargs["rows"]
    assert all(row[1] != "Revolut" for row in written_rows)
    assert len(written_rows) == 3
    assert summary.total_rows_written == 3


def test_run_sync_logs_error_for_failed_bank_without_leaking_document_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    connectors[1].fetch_transactions.side_effect = ReauthorizationRequiredError("re-auth needed")
    writer = Mock(spec=SheetsWriter)

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        run_sync(
            connectors=connectors,
            writer=writer,
            document_id="secret-doc-id",
            today=date(2026, 8, 15),
        )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "Revolut" in message
    assert "re-auth needed" in message
    assert "secret-doc-id" not in message


def test_run_sync_second_execution_does_not_carry_over_previously_failed_bank() -> None:
    """FR-006 / US2 Escenario de Aceptación 5: una ejecución con un banco fallido
    no debe arrastrar datos de ese banco de una ejecución anterior del mismo día.
    """
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        revolut_txs=[Transaction(date(2026, 8, 2), Decimal("-5.00"), "EUR", "Revolut tx")],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    writer = Mock(spec=SheetsWriter)

    run_sync(connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15))
    first_call_rows = writer.write.call_args.kwargs["rows"]
    assert any(row[1] == "Revolut" for row in first_call_rows)

    connectors[1].fetch_transactions.side_effect = ReauthorizationRequiredError("re-auth needed")
    run_sync(connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15))
    second_call_rows = writer.write.call_args.kwargs["rows"]

    assert writer.write.call_count == 2
    assert all(row[1] != "Revolut" for row in second_call_rows)
    assert len(second_call_rows) == 3


# --- US3: terminar de forma controlada cuando ningún banco responde --------


def test_run_sync_all_four_fail_raises_all_banks_failed_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = _four_connectors()
    connectors[0].fetch_transactions.side_effect = ReauthorizationRequiredError("ing boom")
    connectors[1].fetch_transactions.side_effect = RateLimitExceededError("revolut boom")
    connectors[2].fetch_transactions.side_effect = EnableBankingAPIError("myinvestor boom")
    connectors[3].fetch_transactions.side_effect = RuntimeError("sabadell boom")
    writer = Mock(spec=SheetsWriter)

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        with pytest.raises(AllBanksFailedError):
            run_sync(
                connectors=connectors,
                writer=writer,
                document_id="doc-id",
                today=date(2026, 8, 15),
            )

    writer.write.assert_not_called()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    aggregate_messages = "\n".join(r.getMessage() for r in error_records)
    for bank, reason in [
        ("ING España", "ing boom"),
        ("Revolut", "revolut boom"),
        ("MyInvestor", "myinvestor boom"),
        ("Banco Sabadell", "sabadell boom"),
    ]:
        assert bank in aggregate_messages
        assert reason in aggregate_messages


@pytest.mark.parametrize(
    "exc_type",
    [SheetsConfigError, SheetsAccessError, SheetsQuotaExceededError, SheetsAPIError],
)
def test_run_sync_sheets_write_failure_raises_sheets_sync_error(
    exc_type: type[Exception],
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = exc_type("boom")

    with pytest.raises(SheetsSyncError, match="boom"):
        run_sync(
            connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
        )


def test_run_sync_missing_document_id_secret_raises_sheets_sync_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    writer = Mock(spec=SheetsWriter)

    class _FailingSecretStore:
        def get(self, key: str) -> str:
            raise KeyError(key)

    monkeypatch.setattr("banking.sync.SecretStore", _FailingSecretStore)

    with pytest.raises(SheetsSyncError):
        run_sync(connectors=connectors, writer=writer, today=date(2026, 8, 15))

    writer.write.assert_not_called()


def test_run_sync_sheets_failure_logs_error_without_leaking_document_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = SheetsAccessError("no access")

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        with pytest.raises(SheetsSyncError):
            run_sync(
                connectors=connectors,
                writer=writer,
                document_id="secret-doc-id",
                today=date(2026, 8, 15),
            )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) >= 1
    message = " ".join(r.getMessage() for r in error_records)
    assert "sheets" in message.lower()
    assert "secret-doc-id" not in message


# --- IT6: contexto estructurado en las excepciones del pipeline (FR-009) ----


def test_all_banks_failed_error_carries_outcomes_and_tab_name() -> None:
    """A total failure surfaces the four per-bank outcomes, not just a string."""
    connectors = _four_connectors()
    connectors[0].fetch_transactions.side_effect = ReauthorizationRequiredError("ing boom")
    connectors[1].fetch_transactions.side_effect = RateLimitExceededError("revolut boom")
    connectors[2].fetch_transactions.side_effect = EnableBankingAPIError("myinvestor boom")
    connectors[3].fetch_transactions.side_effect = RuntimeError("sabadell boom")

    with pytest.raises(AllBanksFailedError) as excinfo:
        run_sync(
            connectors=connectors,
            writer=Mock(spec=SheetsWriter),
            document_id="doc-id",
            today=date(2026, 8, 15),
        )

    exc = excinfo.value
    assert exc.outcomes is not None
    assert [(o.bank_name, o.succeeded) for o in exc.outcomes] == [
        ("ING España", False),
        ("Revolut", False),
        ("MyInvestor", False),
        ("Banco Sabadell", False),
    ]
    assert [o.failure_reason for o in exc.outcomes] == [
        "ing boom",
        "revolut boom",
        "myinvestor boom",
        "sabadell boom",
    ]
    assert exc.tab_name == "2026-08"
    # Same shape as IT5, with the count taken from the outcomes.
    assert str(exc) == (
        "All 4 banks failed: ING España: ing boom; Revolut: revolut boom; "
        "MyInvestor: myinvestor boom; Banco Sabadell: sabadell boom"
    )


def test_run_sync_translates_a_writer_construction_failure_into_sheets_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building the writer can fail on its own configuration: it is a Sheets error."""
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )

    def exploding_writer() -> SheetsWriter:
        raise SheetsConfigError("GOOGLE_SHEETS_CREDENTIALS is missing")

    monkeypatch.setattr("banking.sync.SheetsWriter", exploding_writer)

    with pytest.raises(SheetsSyncError) as exc_info:
        run_sync(connectors=connectors, document_id="doc-id", today=date(2026, 8, 15))

    assert "GOOGLE_SHEETS_CREDENTIALS is missing" in str(exc_info.value)
    assert exc_info.value.tab_name == "2026-08"


def test_sheets_sync_error_carries_outcomes_and_tab_name() -> None:
    """A Sheets failure keeps the outcomes gathered before the write attempt."""
    connectors = _four_connectors(
        ing_txs=[
            Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx"),
            Transaction(date(2026, 8, 2), Decimal("-3.00"), "EUR", "ING tx 2"),
        ],
        revolut_txs=[Transaction(date(2026, 8, 3), Decimal("-5.00"), "EUR", "Revolut tx")],
    )
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = SheetsAccessError("no access")

    with pytest.raises(SheetsSyncError) as excinfo:
        run_sync(
            connectors=connectors,
            writer=writer,
            document_id="doc-id",
            today=date(2026, 8, 15),
        )

    exc = excinfo.value
    assert exc.outcomes is not None
    assert [(o.bank_name, o.succeeded) for o in exc.outcomes] == [
        ("ING España", True),
        ("Revolut", True),
        ("MyInvestor", True),
        ("Banco Sabadell", True),
    ]
    assert [o.rows_written for o in exc.outcomes] == [2, 1, 0, 0]
    assert exc.tab_name == "2026-08"
    assert str(exc) == "no access"


def test_sheets_sync_error_keeps_failed_bank_outcomes_alongside_sheets_failure() -> None:
    """The combined case (bank failures + Sheets failure) keeps both facts."""
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    connectors[1].fetch_transactions.side_effect = RateLimitExceededError("revolut boom")
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = SheetsAccessError("no access")

    with pytest.raises(SheetsSyncError) as excinfo:
        run_sync(
            connectors=connectors,
            writer=writer,
            document_id="doc-id",
            today=date(2026, 8, 15),
        )

    outcomes = excinfo.value.outcomes
    assert outcomes is not None
    assert [o.succeeded for o in outcomes] == [True, False, True, True]
    assert outcomes[1].failure_reason == "revolut boom"


@pytest.mark.parametrize("exc_class", [AllBanksFailedError, SheetsSyncError])
def test_pipeline_errors_remain_constructible_without_context(
    exc_class: type[Exception],
) -> None:
    """Backwards compatibility: older callers build these with a message only."""
    exc = exc_class("boom")

    assert str(exc) == "boom"
    assert exc.outcomes is None  # type: ignore[attr-defined]
    assert exc.tab_name is None  # type: ignore[attr-defined]


# --- Bancos sin sesión PSD2: un parcial esperado no es un fallo -------------


def _not_onboarded() -> BankNotOnboardedError:
    """Build the error a connector raises for a bank with no PSD2 session."""
    return BankNotOnboardedError("has no PSD2 session configured yet")


def test_bank_outcome_defaults_to_onboarded_and_exposes_failed() -> None:
    """The new field is defaulted and last, so positional construction still works."""
    ok = BankOutcome("ING España", True, 1, None)
    failed = BankOutcome("Revolut", False, None, "boom")
    not_onboarded = BankOutcome("Banco Sabadell", False, None, "no session yet", not_onboarded=True)

    assert ok.not_onboarded is False
    assert ok.failed is False
    assert failed.not_onboarded is False
    assert failed.failed is True
    assert not_onboarded.not_onboarded is True
    assert not_onboarded.failed is False


def test_run_sync_not_onboarded_banks_still_count_as_full_success() -> None:
    """Two banks OK + two without a session: full success, rows only from the OK banks."""
    ing_txs = [Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    revolut_txs = [Transaction(date(2026, 8, 2), Decimal("-5.00"), "EUR", "Revolut tx")]
    connectors = _four_connectors(ing_txs, revolut_txs)
    connectors[2].fetch_transactions.side_effect = _not_onboarded()  # MyInvestor
    connectors[3].fetch_transactions.side_effect = _not_onboarded()  # Banco Sabadell
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    assert summary.total_rows_written == 2
    writer.write.assert_called_once_with(
        document_id="doc-id",
        tab_name="2026-08",
        headers=_HEADERS,
        rows=[
            ["2026-08-01", "ING España", "ING tx", 10.0, "EUR"],
            ["2026-08-02", "Revolut", "Revolut tx", -5.0, "EUR"],
        ],
    )
    by_name = {o.bank_name: o for o in summary.outcomes}
    for name in ("MyInvestor", "Banco Sabadell"):
        outcome = by_name[name]
        assert outcome.not_onboarded is True
        assert outcome.failed is False
        assert outcome.succeeded is False
        assert outcome.rows_written is None
        assert outcome.failure_reason == "has no PSD2 session configured yet"
    assert by_name["ING España"].failed is False


def test_run_sync_logs_a_not_onboarded_bank_at_info_not_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bank without a session is a normal state: nothing is logged as an error."""
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    connectors[2].fetch_transactions.side_effect = _not_onboarded()
    connectors[3].fetch_transactions.side_effect = _not_onboarded()

    with caplog.at_level(logging.INFO, logger="banking.sync"):
        run_sync(
            connectors=connectors,
            writer=Mock(spec=SheetsWriter),
            document_id="doc-id",
            today=date(2026, 8, 15),
        )

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("MyInvestor" in m and "not onboarded" in m.lower() for m in info_messages)


def test_run_sync_all_banks_not_onboarded_writes_nothing() -> None:
    """With no session anywhere the tab is left untouched: writing would clear it."""
    connectors = _four_connectors()
    for connector in connectors:
        connector.fetch_transactions.side_effect = _not_onboarded()
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    assert summary.overall_status == OverallStatus.NOTHING_TO_SYNC
    assert summary.total_rows_written == 0
    assert all(outcome.not_onboarded for outcome in summary.outcomes)
    assert not any(outcome.failed for outcome in summary.outcomes)
    writer.write.assert_not_called()


def test_run_sync_not_onboarded_plus_real_failures_raises_all_banks_failed() -> None:
    """No bank succeeded, but only the two real failures are reported as failures."""
    connectors = _four_connectors()
    connectors[0].fetch_transactions.side_effect = _not_onboarded()  # ING España
    connectors[1].fetch_transactions.side_effect = _not_onboarded()  # Revolut
    connectors[2].fetch_transactions.side_effect = ReauthorizationRequiredError("myinvestor boom")
    connectors[3].fetch_transactions.side_effect = RuntimeError("sabadell boom")
    writer = Mock(spec=SheetsWriter)

    with pytest.raises(AllBanksFailedError) as excinfo:
        run_sync(
            connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
        )

    writer.write.assert_not_called()
    message = str(excinfo.value)
    assert "MyInvestor: myinvestor boom" in message
    assert "Banco Sabadell: sabadell boom" in message
    # The not-onboarded banks are named as context, never as failures.
    assert "ING España: has no PSD2 session" not in message
    assert "Revolut: has no PSD2 session" not in message
    assert "ING España" in message
    assert "Revolut" in message
    assert "not onboarded" in message.lower() or "sin sesión" in message.lower()


def test_run_sync_one_failure_with_one_not_onboarded_bank_is_partial() -> None:
    """One OK + one failed + one without a session + one OK stays a partial failure."""
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        revolut_txs=[Transaction(date(2026, 8, 2), Decimal("-5.00"), "EUR", "Revolut tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    connectors[1].fetch_transactions.side_effect = RateLimitExceededError("revolut boom")
    connectors[2].fetch_transactions.side_effect = _not_onboarded()  # MyInvestor
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    assert summary.overall_status == OverallStatus.PARTIAL_FAILURE
    assert summary.total_rows_written == 2
    by_name = {o.bank_name: o for o in summary.outcomes}
    assert by_name["Revolut"].failed is True
    assert by_name["MyInvestor"].not_onboarded is True
    assert by_name["MyInvestor"].failed is False


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(KeyError("ENABLE_BANKING_SESSION_ID_MYINVESTOR"), id="missing-secret"),
        pytest.param(ConnectorConfigError("eb-config.json is missing"), id="broken-config"),
        pytest.param(
            EnableBankingAPIError("rejected the request parameters (HTTP 422)"),
            id="empty-secret-rejected-by-provider",
        ),
    ],
)
def test_run_sync_any_other_failure_is_never_not_onboarded(
    exc: Exception,
) -> None:
    """The workflow already requires the secrets: an absence is a config break."""
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    connectors[2].fetch_transactions.side_effect = exc  # MyInvestor
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    outcome = next(o for o in summary.outcomes if o.bank_name == "MyInvestor")
    assert outcome.succeeded is False
    assert outcome.not_onboarded is False
    assert outcome.failed is True
    assert summary.overall_status == OverallStatus.PARTIAL_FAILURE


# --- Guarda de invariante: un sync sin conectores no es un exito -------------


@pytest.mark.parametrize(
    "empty_connectors",
    [pytest.param([], id="empty-list"), pytest.param((), id="empty-tuple")],
)
def test_run_sync_requires_at_least_one_connector(
    empty_connectors: Sequence[EnableBankingConnector],
) -> None:
    """An empty connector sequence is a programming error, never a success.

    Reproduces the verified data-loss path: `_classify([])` returned
    FULL_SUCCESS because `all([])` is True, so the run reported success while
    clearing the month's tab by writing zero rows.
    """
    writer = Mock(spec=SheetsWriter)

    with pytest.raises(NoConnectorsError) as excinfo:
        run_sync(
            connectors=empty_connectors,
            writer=writer,
            document_id="doc-id",
            today=date(2026, 8, 15),
        )

    writer.write.assert_not_called()
    assert issubclass(NoConnectorsError, ValueError)
    assert "connector" in str(excinfo.value)


def test_run_sync_rejects_empty_connectors_before_touching_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard fires before any credential lookup, so nothing is read or written."""

    class _ExplodingSecretStore:
        def get(self, key: str) -> str:
            raise AssertionError("SecretStore must not be consulted")

    monkeypatch.setattr("banking.sync.SecretStore", _ExplodingSecretStore)

    with pytest.raises(NoConnectorsError):
        run_sync(connectors=[], document_id=None)
