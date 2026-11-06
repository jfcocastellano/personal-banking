"""CLI handler for the ``banking daily`` subcommand.

``banking daily`` performs the single daily pass: it asks every bank once for
movements and once for its balance, then writes the raw ``<YYYY-MM>`` tab and
the ``<YYYY-MM> Gastos`` layout tab from that same fetch. The command takes no
arguments: the month is always the execution month, and backfills stay in
``banking layout``.

Exit codes mirror ``banking sync``: ``0`` success or nothing to sync, ``1``
total failure (no bank contributed movements and at least one failed for real),
``2`` a Sheets write failed (raw or layout), ``3`` partial failure with at least
one bank written, ``4`` the failure notification could not be delivered.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from banking.daily import (
    BankPass,
    DailySheetsError,
    DailySummary,
    NoBankFetchedError,
    run_daily,
)
from banking.notify import DeliveryStatus, EmailNotifier
from banking.sync import BankOutcome, OverallStatus

_NOTIFICATION_FAILED_MESSAGE = "ERROR (notificación): no se pudo enviar el email de aviso"


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``daily`` subcommand.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    subparsers.add_parser(
        "daily",
        help="Fetch this month once per bank and write the raw and layout tabs",
    )


def handle(
    args: argparse.Namespace,
    notifier: EmailNotifier | None = None,
) -> int:
    """Run the daily pass and print a per-bank report or a failure.

    Args:
        args: Parsed CLI arguments. ``daily`` takes no arguments today; the
            parameter is accepted so this handler has the same shape as the
            other subcommands.
        notifier: Email notifier to use for failures. Injected by tests; a real
            one is built only when a failure actually has to be notified.

    Returns:
        Exit code: ``0`` on full success or when no bank is onboarded (nothing
        was written), ``1`` when no bank could contribute movements and at
        least one failed for real, ``2`` when writing the raw or layout tab
        failed, ``3`` on partial failure (at least one bank written and at least
        one real failure), ``4`` when the failure notification could not be
        delivered.
    """
    try:
        result = run_daily()
    except NoBankFetchedError as exc:
        return _finish_total_failure(notifier, exc)
    except DailySheetsError as exc:
        return _finish_sheets_failure(notifier, exc)

    return _print_summary(result, notifier)


def _succeeded(run: BankPass) -> bool:
    """True when the bank answered for its movements with a PSD2 session in place."""
    return run.transactions_failure is None and not run.not_onboarded


def _movements_label(count: int) -> str:
    """Render the movement count with the right singular/plural noun."""
    return f"{count} movimiento" if count == 1 else f"{count} movimientos"


def _balance_label(run: BankPass) -> str:
    """Render the balance with its bank reference date, or why it is absent."""
    if run.balance_failure is not None:
        return f"FALLÓ la consulta de saldo — {run.balance_failure}"
    if run.balance is None:
        return "sin saldo informado"
    reference = (
        run.balance.reference_date.isoformat()
        if run.balance.reference_date is not None
        else "sin dato de referencia"
    )
    return f"saldo {run.balance.amount} {run.balance.currency} (referencia {reference})"


def _bank_report_line(run: BankPass) -> str:
    """One report line per bank: movements and balance, stated separately."""
    if run.not_onboarded:
        return f"  - {run.bank_name}: SIN SESIÓN PSD2"
    if run.transactions_failure is not None:
        movements = f"FALLÓ la lectura de movimientos — {run.transactions_failure}"
    else:
        movements = _movements_label(len(run.transactions))
    return f"  - {run.bank_name}: {movements}, {_balance_label(run)}"


def _print_report(passes: Sequence[BankPass]) -> None:
    """Print one report line per bank, in the fetched order."""
    for run in passes:
        print(_bank_report_line(run))


def _print_not_onboarded_note(passes: Sequence[BankPass]) -> None:
    """Name the banks without a PSD2 session, worded so it is not read as a failure."""
    names = [run.bank_name for run in passes if run.not_onboarded]
    if not names:
        return
    print(f"  Bancos sin sesión PSD2 (no cuentan como fallo): {', '.join(names)}")


def _print_summary(result: DailySummary, notifier: EmailNotifier | None) -> int:
    """Print the run summary and per-bank report, notifying on partial failure."""
    succeeded = sum(1 for run in result.passes if _succeeded(run))
    total = len(result.passes)

    if result.overall_status is OverallStatus.NOTHING_TO_SYNC:
        exit_code = 0
        print(
            "Pasada diaria omitida: ningún banco tiene sesión PSD2 — "
            f"no se ha escrito nada en las pestañas {result.raw_tab_name} y "
            f"{result.layout_tab_name} ({result.duration_seconds:.2f}s)"
        )
    else:
        if result.overall_status is OverallStatus.FULL_SUCCESS:
            headline = "Pasada diaria completada"
            exit_code = 0
        else:
            headline = "Pasada diaria parcial"
            exit_code = 3

        print(
            f"{headline}: {succeeded}/{total} bancos — "
            f"{result.total_rows_written} movimientos en la pestaña {result.raw_tab_name} y "
            f"{result.expense_count} filas en la pestaña {result.layout_tab_name} "
            f"({result.duration_seconds:.2f}s)"
        )

    _print_report(result.passes)
    _print_not_onboarded_note(result.passes)

    if exit_code == 3:
        notification_exit = _notify_and_exit(
            notifier,
            passes=result.passes,
            sheets_error=None,
            tab_name=result.raw_tab_name,
            duration_seconds=result.duration_seconds,
        )
        if notification_exit is not None:
            return notification_exit
    return exit_code


def _finish_total_failure(notifier: EmailNotifier | None, exc: NoBankFetchedError) -> int:
    """Print the total-failure error, notify, and return the exit code."""
    print(f"ERROR: la pasada diaria falló — {exc}", file=sys.stderr)
    notification_exit = _notify_and_exit(
        notifier,
        passes=exc.passes or [],
        sheets_error=None,
        tab_name=exc.raw_tab_name or _current_raw_tab_name(),
        duration_seconds=0.0,
    )
    return notification_exit if notification_exit is not None else 1


def _finish_sheets_failure(notifier: EmailNotifier | None, exc: DailySheetsError) -> int:
    """Print the Sheets error with its stage, notify, and return the exit code."""
    print(f"ERROR (Sheets, etapa {exc.stage}): {exc}", file=sys.stderr)
    notification_exit = _notify_and_exit(
        notifier,
        passes=exc.passes or [],
        sheets_error=f"etapa {exc.stage}: {exc}",
        tab_name=exc.tab_name or _current_raw_tab_name(),
        duration_seconds=0.0,
    )
    return notification_exit if notification_exit is not None else 2


def _as_outcomes(passes: Sequence[BankPass]) -> list[BankOutcome]:
    """Adapt daily results to the notifier's per-bank outcome type."""
    outcomes: list[BankOutcome] = []
    for run in passes:
        succeeded = _succeeded(run)
        if succeeded:
            failure_reason = None
        elif run.not_onboarded:
            failure_reason = "sin sesión PSD2"
        else:
            failure_reason = run.transactions_failure or run.balance_failure or "unknown failure"
        outcomes.append(
            BankOutcome(
                bank_name=run.bank_name,
                succeeded=succeeded,
                rows_written=len(run.transactions) if succeeded else None,
                failure_reason=failure_reason,
                not_onboarded=run.not_onboarded,
            )
        )
    return outcomes


def _notify_and_exit(
    notifier: EmailNotifier | None,
    passes: Sequence[BankPass],
    sheets_error: str | None,
    tab_name: str,
    duration_seconds: float,
) -> int | None:
    """Send the failure email and translate a delivery failure into exit code 4.

    Returns:
        ``4`` when the delivery failed, ``None`` when it was sent or skipped
        (in which case the caller keeps the daily outcome's exit code).
    """
    email_notifier = notifier if notifier is not None else EmailNotifier()
    status = email_notifier.notify_failure(
        outcomes=_as_outcomes(passes),
        sheets_error=sheets_error,
        tab_name=tab_name,
        duration_seconds=duration_seconds,
    )
    if status is DeliveryStatus.FAILED:
        print(_NOTIFICATION_FAILED_MESSAGE, file=sys.stderr)
        return 4
    return None


def _current_raw_tab_name() -> str:
    """Return this month's raw tab name, used when an exception carries no context."""
    return date.today().strftime("%Y-%m")
