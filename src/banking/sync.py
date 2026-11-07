"""Multi-bank -> Google Sheets synchronization pipeline (IT5)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from banking.config.secret_store import SecretStore
from banking.connectors.enable_banking import (
    BankNotOnboardedError,
    EnableBankingConnector,
    Transaction,
)
from banking.connectors.ing import IngConnector
from banking.connectors.myinvestor import MyInvestorConnector
from banking.connectors.revolut import RevolutConnector
from banking.connectors.sabadell import SabadellConnector
from banking.run_summary import total_failure_message
from banking.sheets.writer import CellValue, SheetsWriter

logger = logging.getLogger(__name__)

_SHEET_ID_KEY = "GOOGLE_SHEET_ID"
_HEADERS: list[CellValue] = ["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"]
_CONNECTOR_CLASSES: tuple[type[EnableBankingConnector], ...] = (
    IngConnector,
    RevolutConnector,
    MyInvestorConnector,
    SabadellConnector,
)


class AllBanksFailedError(Exception):
    """Raised when every bank connector fails; nothing is written to Sheets.

    Attributes:
        outcomes: The per-bank outcomes of the failed run, or ``None`` when the
            raiser did not provide context (kept for backwards compatibility).
        tab_name: The destination tab of the run, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        outcomes: list[BankOutcome] | None = None,
        tab_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.outcomes = outcomes
        self.tab_name = tab_name


class NoConnectorsError(ValueError):
    """Raised when a sync run is requested without any bank connector.

    A programming error rather than a runtime failure: an empty connector
    sequence would otherwise classify as ``FULL_SUCCESS`` (because ``all([])``
    is true) and clear the month's tab by writing zero rows.
    """


class SheetsSyncError(Exception):
    """Raised when writing to Google Sheets fails; wraps the original writer error.

    Attributes:
        outcomes: The per-bank outcomes gathered before the failed write, or
            ``None`` when the raiser did not provide context.
        tab_name: The destination tab of the run, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        outcomes: list[BankOutcome] | None = None,
        tab_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.outcomes = outcomes
        self.tab_name = tab_name


class OverallStatus(Enum):
    """The four possible outcomes of a sync run."""

    FULL_SUCCESS = "full_success"
    PARTIAL_FAILURE = "partial_failure"
    TOTAL_FAILURE = "total_failure"
    NOTHING_TO_SYNC = "nothing_to_sync"
    """No bank is onboarded yet: nothing failed, and nothing may be written."""


@dataclass(frozen=True)
class BankOutcome:
    """The outcome of running one bank's connector in a sync run.

    ``not_onboarded`` marks a bank that simply has no PSD2 session yet: it is a
    normal state, so it is neither a success nor a failure. ``failed`` is the
    only thing the run classification counts.
    """

    bank_name: str
    succeeded: bool
    rows_written: int | None
    failure_reason: str | None
    not_onboarded: bool = False

    @property
    def failed(self) -> bool:
        """Return True only for a real failure (a bank that had to sync and could not)."""
        return not self.succeeded and not self.not_onboarded


@dataclass(frozen=True)
class SyncSummary:
    """The aggregate outcome of a sync run across all bank connectors."""

    outcomes: list[BankOutcome]
    overall_status: OverallStatus
    tab_name: str
    total_rows_written: int
    duration_seconds: float


def transaction_rows(bank_name: str, transactions: list[Transaction]) -> list[list[CellValue]]:
    """Convert transactions to rows matching `_HEADERS`, in fixed column order."""
    return [
        [tx.booking_date.isoformat(), bank_name, tx.description, float(tx.amount), tx.currency]
        for tx in transactions
    ]


def _classify(outcomes: list[BankOutcome]) -> OverallStatus:
    """Classify the aggregate result of a sync run from its per-bank outcomes.

    Only real failures decide: a bank with no PSD2 session yet is a normal
    state, so a run where nothing failed is a full success even if some banks
    are merely not onboarded.
    """
    failed = [o for o in outcomes if o.failed]
    if not failed:
        return OverallStatus.FULL_SUCCESS
    if any(o.succeeded for o in outcomes):
        return OverallStatus.PARTIAL_FAILURE
    return OverallStatus.TOTAL_FAILURE


def _sync_one_bank(
    connector: EnableBankingConnector, start_date: date, end_date: date
) -> tuple[BankOutcome, list[Transaction]]:
    """Run one bank's connector, translating any failure into a `BankOutcome`."""
    try:
        transactions = connector.fetch_transactions(start_date, end_date)
    except BankNotOnboardedError as exc:
        # A bank without a PSD2 session is a normal state, not a failure: log it
        # at INFO so the run stays quiet until the consent exists.
        logger.info(
            "Sync skipped: bank=%s not onboarded (no PSD2 session yet) reason=%s",
            connector.BANK_NAME,
            exc,
        )
        return (
            BankOutcome(
                bank_name=connector.BANK_NAME,
                succeeded=False,
                rows_written=None,
                failure_reason=str(exc),
                not_onboarded=True,
            ),
            [],
        )
    except Exception as exc:
        logger.error(
            "Sync failed: bank=%s reason=%s",
            connector.BANK_NAME,
            exc,
        )
        return (
            BankOutcome(
                bank_name=connector.BANK_NAME,
                succeeded=False,
                rows_written=None,
                failure_reason=str(exc),
            ),
            [],
        )
    return (
        BankOutcome(
            bank_name=connector.BANK_NAME,
            succeeded=True,
            rows_written=len(transactions),
            failure_reason=None,
        ),
        transactions,
    )


def run_sync(
    connectors: Sequence[EnableBankingConnector] | None = None,
    writer: SheetsWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> SyncSummary:
    """Fetch this month's movements from all four banks and write the successful ones.

    Runs each bank connector independently, in the fixed ING/Revolut/MyInvestor/
    Sabadell order. A single connector's failure does not abort the run.

    Raises:
        NoConnectorsError: ``connectors`` was an empty sequence. Nothing is
            read, fetched or written.
        SheetsSyncError: writing the combined rows to Google Sheets failed
            (including resolving the destination document ID), after at
            least one bank succeeded.

    When no bank is onboarded (every connector reported a missing PSD2 session),
    the run finishes with `OverallStatus.NOTHING_TO_SYNC` and the destination tab
    is left untouched: writing an empty sheet would clear it.
    """
    start = time.monotonic()
    execution_date = today or date.today()
    range_start = execution_date.replace(day=1)
    tab_name = execution_date.strftime("%Y-%m")

    resolved_connectors: Sequence[EnableBankingConnector] = (
        connectors if connectors is not None else [cls() for cls in _CONNECTOR_CLASSES]
    )
    if not resolved_connectors:
        raise NoConnectorsError("run_sync requires at least one bank connector.")

    outcomes: list[BankOutcome] = []
    rows: list[list[CellValue]] = []
    for connector in resolved_connectors:
        outcome, transactions = _sync_one_bank(connector, range_start, execution_date)
        outcomes.append(outcome)
        rows.extend(transaction_rows(outcome.bank_name, transactions))

    overall_status = _classify(outcomes)

    if overall_status == OverallStatus.TOTAL_FAILURE:
        failed = [o for o in outcomes if o.failed]
        not_onboarded = [o for o in outcomes if o.not_onboarded]
        aggregate = "; ".join(f"{o.bank_name}: {o.failure_reason}" for o in failed)
        logger.error(
            "Sync failed: banks_failed=%d banks_not_onboarded=%d: %s",
            len(failed),
            len(not_onboarded),
            aggregate,
        )
        raise AllBanksFailedError(
            total_failure_message(failed, not_onboarded),
            outcomes=outcomes,
            tab_name=tab_name,
        )

    if not any(o.succeeded for o in outcomes):
        # Every bank is merely not onboarded. Nothing failed, but nothing may be
        # written either: the writer clears the tab before filling it, so running
        # it here would erase a month that no bank contributed to.
        duration = time.monotonic() - start
        logger.info(
            "Sync skipped: no bank is onboarded tab=%s banks=%d duration=%.3fs",
            tab_name,
            len(outcomes),
            duration,
        )
        return SyncSummary(
            outcomes=outcomes,
            overall_status=OverallStatus.NOTHING_TO_SYNC,
            tab_name=tab_name,
            total_rows_written=0,
            duration_seconds=duration,
        )

    try:
        resolved_document_id = (
            document_id if document_id is not None else SecretStore().get(_SHEET_ID_KEY)
        )
        resolved_writer = writer or SheetsWriter()
        resolved_writer.write(
            document_id=resolved_document_id, tab_name=tab_name, headers=_HEADERS, rows=rows
        )
    except Exception as exc:
        logger.error("Sync failed: system=sheets tab=%s reason=%s", tab_name, exc)
        raise SheetsSyncError(str(exc), outcomes=outcomes, tab_name=tab_name) from exc

    duration = time.monotonic() - start
    total_rows_written = sum(o.rows_written or 0 for o in outcomes)
    logger.info(
        "Sync succeeded: status=%s tab=%s rows_written=%d duration=%.3fs",
        overall_status.value,
        tab_name,
        total_rows_written,
        duration,
    )
    return SyncSummary(
        outcomes=outcomes,
        overall_status=overall_status,
        tab_name=tab_name,
        total_rows_written=total_rows_written,
        duration_seconds=duration,
    )
