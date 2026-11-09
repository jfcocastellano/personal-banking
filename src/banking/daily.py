"""Domain layer of the single daily pass: one fetch per bank and stage.

The daily pass queries every bank exactly once for movements and once for the
balance, so it stays inside the PSD2 request budget, then writes the raw month
and the layout month from that single fetch. It reuses ``banking.sync``'s
connector list, exceptions and status enum so both commands classify a run the
same way.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from banking.config.secret_store import SecretStore
from banking.connectors.enable_banking import (
    Balance,
    BankNotOnboardedError,
    EnableBankingConnector,
    Transaction,
)
from banking.run_summary import total_failure_message
from banking.sheets.layout import (
    LayoutWriter,
    balances_from_banks,
    expense_rows_from_banks,
    layout_tab_name,
)
from banking.sheets.writer import SheetsWriter
from banking.sync import (
    _CONNECTOR_CLASSES,
    _HEADERS,
    _SHEET_ID_KEY,
    NoConnectorsError,
    OverallStatus,
    transaction_rows_for_banks,
)

logger = logging.getLogger(__name__)

#: Which of the two writes failed when the daily pass could not reach Sheets.
WriteStage = Literal["raw", "layout"]


@dataclass(frozen=True)
class BankPass:
    """The raw result of querying one bank once for movements and once for balance.

    Each stage fails on its own: a transactions failure leaves ``balance``
    populated and vice versa. ``not_onboarded`` marks a bank without a PSD2
    session yet, which is an expected state rather than a failure, so in that
    case both ``*_failure`` fields stay ``None``.
    """

    bank_name: str
    transactions: tuple[Transaction, ...] = ()
    balance: Balance | None = None
    transactions_failure: str | None = None
    balance_failure: str | None = None
    not_onboarded: bool = False

    @property
    def failure_reason(self) -> str:
        """The bank's own failure reason, for the aggregate failure message."""
        return self.transactions_failure or self.balance_failure or "unknown failure"


@dataclass(frozen=True)
class DailySummary:
    """The aggregate outcome of one daily pass across every bank.

    ``total_rows_written`` counts the rows handed to the raw tab, and
    ``expense_count``/``balance_count`` the rows handed to the layout tab, so a
    reader can check that both tabs carry the same movement set.
    """

    passes: list[BankPass]
    overall_status: OverallStatus
    raw_tab_name: str
    layout_tab_name: str
    total_rows_written: int
    expense_count: int
    balance_count: int
    duration_seconds: float


class NoBankFetchedError(Exception):
    """Raised when no bank could contribute movements to the daily pass.

    Nothing is written in this case: writing would clear a month that no bank
    answered for. Banks without a PSD2 session are reported as such, never as
    failures.

    Attributes:
        passes: The per-bank results of the failed run, or ``None`` when the
            raiser did not provide context.
        raw_tab_name: The raw tab that was not written, or ``None``.
        layout_tab_name: The layout tab that was not written, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        passes: list[BankPass] | None = None,
        raw_tab_name: str | None = None,
        layout_tab_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.passes = passes
        self.raw_tab_name = raw_tab_name
        self.layout_tab_name = layout_tab_name


class DailySheetsError(Exception):
    """Raised when writing one of the two tabs fails; wraps the writer error.

    Attributes:
        passes: The per-bank results gathered before the failed write, or
            ``None`` when the raiser did not provide context.
        stage: Which write failed: the raw tab (``"raw"``) or the layout tab
            (``"layout"``).
        tab_name: The tab that could not be written, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: WriteStage,
        passes: list[BankPass] | None = None,
        tab_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.passes = passes
        self.stage = stage
        self.tab_name = tab_name


def _log_not_onboarded(bank_name: str, stage: str, exc: BankNotOnboardedError) -> None:
    """Log a missing PSD2 session at INFO: it is an expected state, not an error."""
    logger.info(
        "Daily pass skipped stage: bank=%s stage=%s not onboarded (no PSD2 session yet) reason=%s",
        bank_name,
        stage,
        exc,
    )


def _log_stage_failure(bank_name: str, stage: str, exc: Exception) -> None:
    """Log a real stage failure at ERROR, naming the bank and the failed stage."""
    logger.error(
        "Daily pass stage failed: bank=%s stage=%s reason=%s",
        bank_name,
        stage,
        exc,
    )


def collect_bank_runs(
    connectors: Sequence[EnableBankingConnector],
    *,
    start_date: date,
    end_date: date,
) -> tuple[BankPass, ...]:
    """Query each bank once for movements and once for its current balance.

    Both stages run for every bank, in the order the connectors were given: a
    transactions failure never skips the balance, and a balance failure never
    discards the movements. Exceptions other than `BankNotOnboardedError` are
    captured in the matching ``*_failure`` field instead of aborting the loop.

    Args:
        connectors: The bank connectors to query, in the desired output order.
        start_date: First movement booking date to request, inclusive.
        end_date: Last movement booking date to request, inclusive.

    Returns:
        One `BankPass` per connector, in the same order as ``connectors``.
    """
    runs: list[BankPass] = []
    for connector in connectors:
        bank_name = connector.BANK_NAME
        transactions: tuple[Transaction, ...] = ()
        transactions_failure: str | None = None
        balance: Balance | None = None
        balance_failure: str | None = None
        not_onboarded = False

        try:
            transactions = tuple(connector.fetch_transactions(start_date, end_date))
        except BankNotOnboardedError as exc:
            not_onboarded = True
            _log_not_onboarded(bank_name, "transactions", exc)
        except Exception as exc:
            transactions_failure = str(exc)
            _log_stage_failure(bank_name, "transactions", exc)

        try:
            balance = connector.fetch_balance()
        except BankNotOnboardedError as exc:
            not_onboarded = True
            _log_not_onboarded(bank_name, "balance", exc)
        except Exception as exc:
            balance_failure = str(exc)
            _log_stage_failure(bank_name, "balance", exc)

        runs.append(
            BankPass(
                bank_name=bank_name,
                transactions=transactions,
                balance=balance,
                transactions_failure=transactions_failure,
                balance_failure=balance_failure,
                not_onboarded=not_onboarded,
            )
        )

    return tuple(runs)


def _succeeded(run: BankPass) -> bool:
    """True when the bank answered for its movements with a PSD2 session in place.

    Mirrors `banking.sync.BankOutcome.succeeded`: a bank that answered with zero
    movements still succeeded.
    """
    return run.transactions_failure is None and not run.not_onboarded


def _failed(run: BankPass) -> bool:
    """True only for a real failure: a bank that had to answer and could not."""
    return not _succeeded(run) and not run.not_onboarded


def _classify(passes: list[BankPass]) -> OverallStatus:
    """Classify the pass with `sync`'s semantics plus the nothing-to-sync state.

    A bank without a PSD2 session yet is a normal state, so it counts as
    neither a success nor a failure. Only real failures decide between
    `PARTIAL_FAILURE` and `TOTAL_FAILURE`, and a run with neither failures nor
    successes may write nothing at all (`NOTHING_TO_SYNC`).
    """
    failed = [run for run in passes if _failed(run)]
    succeeded = [run for run in passes if _succeeded(run)]
    if failed:
        return OverallStatus.PARTIAL_FAILURE if succeeded else OverallStatus.TOTAL_FAILURE
    if not succeeded:
        return OverallStatus.NOTHING_TO_SYNC
    return OverallStatus.FULL_SUCCESS


def run_daily(
    *,
    connectors: Sequence[EnableBankingConnector] | None = None,
    writer: SheetsWriter | None = None,
    layout_writer: LayoutWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> DailySummary:
    """Fetch this month from every bank once and write the raw and layout tabs.

    The month is the execution month: ``<YYYY-MM>`` for the raw tab and
    ``<YYYY-MM> Gastos`` for the layout. Both tabs are written from the same
    single fetch, so each bank is queried once for movements and once for its
    balance.

    Raises:
        NoConnectorsError: ``connectors`` was an empty sequence. Nothing is
            read, fetched or written.
        NoBankFetchedError: no bank could contribute movements and at least one
            failed for real. Nothing is written, so an existing month survives.
        DailySheetsError: resolving the document ID, writing the raw tab
            (``stage="raw"``) or writing the layout tab (``stage="layout"``)
            failed. A raw failure leaves the layout untouched.

    When every bank is merely not onboarded (no PSD2 session yet), the run
    finishes with `OverallStatus.NOTHING_TO_SYNC` and no tab is touched: the
    writers clear a tab before filling it, so writing here would erase a month
    that no bank contributed to. The spreadsheet secret is not even read.
    """
    start = time.monotonic()
    execution_date = today or date.today()
    month_start = execution_date.replace(day=1)
    raw_tab_name = execution_date.strftime("%Y-%m")
    target_layout_tab = layout_tab_name(month_start)

    resolved_connectors: Sequence[EnableBankingConnector] = (
        connectors if connectors is not None else [cls() for cls in _CONNECTOR_CLASSES]
    )
    if not resolved_connectors:
        raise NoConnectorsError("run_daily requires at least one bank connector.")

    passes = list(
        collect_bank_runs(resolved_connectors, start_date=month_start, end_date=execution_date)
    )
    overall_status = _classify(passes)

    if overall_status == OverallStatus.TOTAL_FAILURE:
        failed = [run for run in passes if _failed(run)]
        not_onboarded = [run for run in passes if run.not_onboarded]
        logger.error(
            "Daily pass failed: banks_failed=%d banks_not_onboarded=%d: %s",
            len(failed),
            len(not_onboarded),
            "; ".join(f"{run.bank_name}: {run.failure_reason}" for run in failed),
        )
        raise NoBankFetchedError(
            total_failure_message(failed, not_onboarded),
            passes=passes,
            raw_tab_name=raw_tab_name,
            layout_tab_name=target_layout_tab,
        )

    if overall_status == OverallStatus.NOTHING_TO_SYNC:
        duration = time.monotonic() - start
        logger.info(
            "Daily pass skipped: no bank is onboarded raw_tab=%s layout_tab=%s banks=%d "
            "duration=%.3fs",
            raw_tab_name,
            target_layout_tab,
            len(passes),
            duration,
        )
        return DailySummary(
            passes=passes,
            overall_status=overall_status,
            raw_tab_name=raw_tab_name,
            layout_tab_name=target_layout_tab,
            total_rows_written=0,
            expense_count=0,
            balance_count=0,
            duration_seconds=duration,
        )

    raw_rows = transaction_rows_for_banks([(run.bank_name, run.transactions) for run in passes])
    expense_rows = expense_rows_from_banks(passes)
    balances = balances_from_banks(passes)

    try:
        resolved_document_id = (
            document_id if document_id is not None else SecretStore().get(_SHEET_ID_KEY)
        )
        resolved_writer = writer if writer is not None else SheetsWriter()
        resolved_writer.write(
            document_id=resolved_document_id,
            tab_name=raw_tab_name,
            headers=_HEADERS,
            rows=raw_rows,
        )
    except Exception as exc:
        logger.error(
            "Daily pass failed: system=sheets stage=raw tab=%s reason=%s", raw_tab_name, exc
        )
        raise DailySheetsError(str(exc), stage="raw", passes=passes, tab_name=raw_tab_name) from exc

    try:
        resolved_layout_writer = layout_writer if layout_writer is not None else LayoutWriter()
        resolved_layout_writer.write(
            document_id=resolved_document_id,
            tab_name=target_layout_tab,
            transactions=expense_rows,
            balances=balances,
        )
    except Exception as exc:
        logger.error(
            "Daily pass failed: system=sheets stage=layout tab=%s reason=%s",
            target_layout_tab,
            exc,
        )
        raise DailySheetsError(
            str(exc), stage="layout", passes=passes, tab_name=target_layout_tab
        ) from exc

    duration = time.monotonic() - start
    logger.info(
        "Daily pass succeeded: status=%s raw_tab=%s layout_tab=%s rows_written=%d "
        "balance_rows=%d balances_reported=%d duration=%.3fs",
        overall_status.value,
        raw_tab_name,
        target_layout_tab,
        len(raw_rows),
        len(balances),
        sum(1 for balance in balances if balance.amount is not None),
        duration,
    )
    return DailySummary(
        passes=passes,
        overall_status=overall_status,
        raw_tab_name=raw_tab_name,
        layout_tab_name=target_layout_tab,
        total_rows_written=len(raw_rows),
        expense_count=len(expense_rows),
        balance_count=len(balances),
        duration_seconds=duration,
    )
