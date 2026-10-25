"""CLI handler for the ``banking layout`` subcommand.

``banking layout`` turns a month of bank data into the ``<YYYY-MM> Gastos``
layout tab. Transactions and balances are fetched per bank, each inside its own
``try``, so a transaction failure and a balance failure are reported separately
and neither aborts the run (FR-011, plan.md "Failure isolation").

Exit codes: ``0`` when the layout tab was written, ``1`` when writing it failed,
``2`` on an invalid ``--month``, ``3`` when no bank could fetch transactions (the
expense block is then left untouched instead of being emptied).
"""

from __future__ import annotations

import argparse
import calendar
import logging
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from banking.config.secret_store import SecretStore
from banking.connectors.enable_banking import Balance, EnableBankingConnector, Transaction
from banking.sheets.layout import AccountBalance, ExpenseRow, LayoutWriter
from banking.sync import _CONNECTOR_CLASSES

logger = logging.getLogger(__name__)

_SHEET_ID_KEY = "GOOGLE_SHEET_ID"
_LAYOUT_TAB_SUFFIX = " Gastos"
_MONTH_PATTERN = re.compile(r"(\d{4})-(\d{2})")

EXIT_OK = 0
EXIT_WRITE_FAILED = 1
EXIT_INVALID_MONTH = 2
EXIT_NOTHING_FETCHED = 3


class NothingFetchedError(Exception):
    """Raised when no bank could fetch transactions, so no layout is written.

    Writing in that case would clear an existing month's expense block and
    present a blank sheet as if the month had no movements.

    Attributes:
        outcomes: The per-bank outcomes of the failed run.
        tab_name: The layout tab that was not written.
    """

    def __init__(
        self,
        message: str,
        *,
        outcomes: list[BankRun] | None = None,
        tab_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.outcomes = outcomes
        self.tab_name = tab_name


class LayoutWriteError(Exception):
    """Raised when writing the layout tab fails; wraps the original writer error.

    Attributes:
        outcomes: The per-bank outcomes gathered before the failed write.
        tab_name: The layout tab that could not be written.
    """

    def __init__(
        self,
        message: str,
        *,
        outcomes: list[BankRun] | None = None,
        tab_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.outcomes = outcomes
        self.tab_name = tab_name


@dataclass(frozen=True)
class BankRun:
    """What one bank contributed to the layout, and what it failed to provide.

    ``transactions_failure``/``balance_failure`` are ``None`` when the stage
    succeeded. A ``balance`` of ``None`` with no failure means the bank simply
    reported no usable balance; that is not an error.
    """

    bank_name: str
    transactions: Sequence[Transaction]
    transactions_failure: str | None
    balance: Balance | None
    balance_failure: str | None


@dataclass(frozen=True)
class LayoutSummary:
    """The aggregate outcome of a layout run."""

    tab_name: str
    outcomes: list[BankRun]
    expense_count: int
    balance_count: int
    duration_seconds: float


def _month_error(raw: str) -> str:
    return f"mes no válido «{raw}»: se esperaba YYYY-MM, por ejemplo 2026-08"


def _month_start(raw: str) -> date:
    """Return the first day of ``raw``, which must be exactly ``YYYY-MM``.

    Raises:
        ValueError: on any other shape or on a month outside 01..12.
    """
    match = _MONTH_PATTERN.fullmatch(raw)
    if match is None:
        raise ValueError(_month_error(raw))
    year, month = (int(part) for part in match.groups())
    try:
        return date(year, month, 1)
    except ValueError as exc:
        raise ValueError(_month_error(raw)) from exc


def _month_argument(raw: str) -> date:
    """argparse ``type`` wrapper: a bad value exits 2 with a usage-style message."""
    try:
        return _month_start(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _resolve_month(raw: object) -> date:
    """Normalize ``--month`` (already parsed by argparse, or absent) to a date.

    Raises:
        ValueError: when ``raw`` is a string that is not ``YYYY-MM``.
    """
    if raw is None:
        return date.today().replace(day=1)
    if isinstance(raw, date):
        return raw.replace(day=1)
    return _month_start(str(raw))


def _month_range(month_start: date, today: date) -> tuple[date, date]:
    """Return the first and last day to request for ``month_start``.

    The last day is the month's last day, capped at ``today`` for the current
    month so the range never reaches into the future.
    """
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    if (month_start.year, month_start.month) == (today.year, today.month):
        return month_start, min(month_end, today)
    return month_start, month_end


def _tab_name(month_start: date) -> str:
    return f"{month_start.strftime('%Y-%m')}{_LAYOUT_TAB_SUFFIX}"


def _failure_reason(exc: Exception) -> str:
    """A human-readable reason even for exceptions raised without a message."""
    return str(exc) or type(exc).__name__


def _run_one_bank(connector: EnableBankingConnector, start_date: date, end_date: date) -> BankRun:
    """Fetch one bank's transactions and balance, isolating each stage."""
    try:
        transactions: list[Transaction] = connector.fetch_transactions(start_date, end_date)
        transactions_failure = None
    except Exception as exc:
        logger.error(
            "Layout failed: bank=%s stage=transactions reason=%s",
            connector.BANK_NAME,
            exc,
        )
        transactions = []
        transactions_failure = _failure_reason(exc)

    try:
        balance: Balance | None = connector.fetch_balance()
        balance_failure = None
    except Exception as exc:
        logger.error(
            "Layout failed: bank=%s stage=balance reason=%s",
            connector.BANK_NAME,
            exc,
        )
        balance = None
        balance_failure = _failure_reason(exc)

    return BankRun(
        bank_name=connector.BANK_NAME,
        transactions=transactions,
        transactions_failure=transactions_failure,
        balance=balance,
        balance_failure=balance_failure,
    )


def _expense_rows(outcomes: Sequence[BankRun]) -> list[ExpenseRow]:
    """The individual-expenses block: every transaction of every bank."""
    return [
        ExpenseRow(
            booking_date=transaction.booking_date,
            bank=outcome.bank_name,
            description=transaction.description,
            amount=transaction.amount,
        )
        for outcome in outcomes
        for transaction in outcome.transactions
    ]


def _account_balances(outcomes: Sequence[BankRun]) -> list[AccountBalance]:
    """One balance row per connector-backed account, empty when unreported."""
    return [
        AccountBalance(
            bank=outcome.bank_name,
            amount=outcome.balance.amount if outcome.balance is not None else None,
            currency=outcome.balance.currency if outcome.balance is not None else "EUR",
            reference_date=outcome.balance.reference_date if outcome.balance is not None else None,
        )
        for outcome in outcomes
    ]


def run_layout(
    *,
    month: date | None = None,
    connectors: Sequence[EnableBankingConnector] | None = None,
    writer: LayoutWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> LayoutSummary:
    """Fetch one month from every bank and write the ``<YYYY-MM> Gastos`` tab.

    Runs each connector in the fixed ING/Revolut/MyInvestor/Sabadell order. A
    bank's transaction failure or balance failure is reported and never aborts
    the run; the layout is written once with whatever succeeded.

    Raises:
        NothingFetchedError: no bank could fetch transactions. Nothing is
            written, so an existing month's expense block stays intact.
        LayoutWriteError: resolving the document ID or writing the tab failed.
    """
    start = time.monotonic()
    execution_date = today or date.today()
    month_start = (month or execution_date).replace(day=1)
    range_start, range_end = _month_range(month_start, execution_date)
    tab_name = _tab_name(month_start)

    resolved_connectors: Sequence[EnableBankingConnector] = (
        connectors if connectors is not None else [cls() for cls in _CONNECTOR_CLASSES]
    )

    outcomes = [
        _run_one_bank(connector, range_start, range_end) for connector in resolved_connectors
    ]

    if not any(outcome.transactions_failure is None for outcome in outcomes):
        logger.error("Layout failed: tab=%s reason=no bank could fetch transactions", tab_name)
        raise NothingFetchedError(
            f"no bank could fetch transactions for {tab_name}",
            outcomes=outcomes,
            tab_name=tab_name,
        )

    expense_rows = _expense_rows(outcomes)
    balances = _account_balances(outcomes)
    layout_writer = writer if writer is not None else LayoutWriter()

    try:
        resolved_document_id = (
            document_id if document_id is not None else SecretStore().get(_SHEET_ID_KEY)
        )
        layout_writer.write(
            document_id=resolved_document_id,
            tab_name=tab_name,
            transactions=expense_rows,
            balances=balances,
        )
    except Exception as exc:
        logger.error("Layout failed: tab=%s reason=%s", tab_name, exc)
        raise LayoutWriteError(str(exc), outcomes=outcomes, tab_name=tab_name) from exc

    duration = time.monotonic() - start
    logger.info(
        "Layout succeeded: tab=%s movements=%d balance_rows=%d duration=%.3fs",
        tab_name,
        len(expense_rows),
        len(balances),
        duration,
    )
    return LayoutSummary(
        tab_name=tab_name,
        outcomes=outcomes,
        expense_count=len(expense_rows),
        balance_count=len(balances),
        duration_seconds=duration,
    )


def _movements_label(count: int) -> str:
    return f"{count} movimiento" if count == 1 else f"{count} movimientos"


def _bank_report_line(outcome: BankRun) -> str:
    """One report line per bank, stating transactions and balance separately."""
    parts: list[str] = []
    if outcome.transactions_failure is not None:
        parts.append(f"FALLÓ la lectura de movimientos — {outcome.transactions_failure}")
    else:
        parts.append(_movements_label(len(outcome.transactions)))

    if outcome.balance_failure is not None:
        parts.append(f"FALLÓ la consulta de saldo — {outcome.balance_failure}")
    elif outcome.balance is None:
        parts.append("sin saldo informado")
    else:
        parts.append(f"saldo {outcome.balance.amount} {outcome.balance.currency}")

    return f"  - {outcome.bank_name}: " + ", ".join(parts)


def _print_report(outcomes: Sequence[BankRun]) -> None:
    for outcome in outcomes:
        print(_bank_report_line(outcome))


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``layout`` subcommand.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    parser = subparsers.add_parser(
        "layout",
        help="Genera la pestaña de gastos del mes (<YYYY-MM> Gastos)",
    )
    parser.add_argument(
        "--month",
        metavar="YYYY-MM",
        type=_month_argument,
        default=None,
        help="Mes a generar, exactamente YYYY-MM (por defecto: el mes actual)",
    )


def handle(args: argparse.Namespace) -> int:
    """Run the layout pipeline and print the per-bank report.

    Args:
        args: Parsed CLI arguments; ``--month`` is a ``date`` or ``None``.

    Returns:
        Exit code: ``0`` when the layout tab was written, ``1`` when writing it
        failed, ``2`` on an invalid ``--month``, ``3`` when no bank could fetch
        transactions. Balance failures never change the exit code.
    """
    try:
        month = _resolve_month(getattr(args, "month", None))
    except ValueError as exc:
        print(f"ERROR (layout): {exc}", file=sys.stderr)
        return EXIT_INVALID_MONTH

    try:
        summary = run_layout(month=month)
    except NothingFetchedError as exc:
        _print_report(exc.outcomes or [])
        print(
            "ERROR (layout): ningún banco pudo leer los movimientos — "
            f"no se ha escrito la pestaña {exc.tab_name}",
            file=sys.stderr,
        )
        return EXIT_NOTHING_FETCHED
    except LayoutWriteError as exc:
        _print_report(exc.outcomes or [])
        print(
            f"ERROR (layout): no se pudo escribir la pestaña {exc.tab_name}: {exc}",
            file=sys.stderr,
        )
        return EXIT_WRITE_FAILED

    _print_report(summary.outcomes)
    print(
        f"Layout completado: {_movements_label(summary.expense_count)} y "
        f"{summary.balance_count} saldos escritos en la pestaña {summary.tab_name} "
        f"({summary.duration_seconds:.2f}s)"
    )
    return EXIT_OK
