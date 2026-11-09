"""CLI handler for the ``banking daily`` subcommand.

``banking daily`` performs the single daily pass: it asks every bank once for
movements and once for its balance, then writes the raw ``<YYYY-MM>`` tab and
the ``<YYYY-MM> Gastos`` layout tab from that same fetch. The month is always
the execution month: the command has no month parameter, and backfills stay in
``banking layout``. Its one option, ``--summary-json PATH``, only writes a JSON
copy of the run summary; it never changes what the command prints.

Exit codes mirror ``banking sync``: ``0`` success or nothing to sync, ``1``
total failure (no bank contributed movements and at least one failed for real),
``2`` a Sheets write failed (raw or layout), ``3`` partial failure with at least
one bank written, ``4`` the failure notification could not be delivered.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from banking.cli.common import current_tab_name, notify_and_exit, print_not_onboarded_note
from banking.daily import (
    BankPass,
    DailySheetsError,
    DailySummary,
    NoBankFetchedError,
    _succeeded,
    run_daily,
)
from banking.notify import EmailNotifier
from banking.summary_file import (
    build_payload,
    build_sheets_failure_payload,
    build_total_failure_payload,
    write_summary_file,
)
from banking.sync import BankOutcome, OverallStatus

# Prefix for the reason a succeeded bank still carries: its movements arrived,
# so the run is not failed, but the balance the run could not read is not
# silently dropped from the failure email.
_BALANCE_FAILURE_REASON = "saldo no disponible"

#: Exit code of a partial failure, the only terminal path that notifies.
_PARTIAL_FAILURE_EXIT = 3


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``daily`` subcommand.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    parser = subparsers.add_parser(
        "daily",
        help="Fetch this month once per bank and write the raw and layout tabs",
    )
    parser.add_argument(
        "--summary-json",
        metavar="PATH",
        default=None,
        help="Write one JSON run summary to PATH (stdout stays unchanged)",
    )


def handle(
    args: argparse.Namespace,
    notifier: EmailNotifier | None = None,
) -> int:
    """Run the daily pass and print a per-bank report or a failure.

    Args:
        args: Parsed CLI arguments. ``daily`` only carries the optional
            ``--summary-json`` path, so a ``Namespace`` without it still works.
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
    summary_path: str | Path | None = getattr(args, "summary_json", None)
    try:
        result = run_daily()
    except NoBankFetchedError as exc:
        return _finish_total_failure(notifier, exc, summary_path)
    except DailySheetsError as exc:
        return _finish_sheets_failure(notifier, exc, summary_path)

    return _print_summary(result, notifier, summary_path)


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


def _completion_headline(result: DailySummary, succeeded: int, total: int) -> tuple[str, int]:
    """The exact summary line of a completed run, and the exit code it implies.

    This is the single definition of the sentence `banking daily` prints on the
    success and nothing-to-sync paths, so the JSON document repeats it verbatim
    instead of re-rendering it.
    """
    if result.overall_status is OverallStatus.NOTHING_TO_SYNC:
        return (
            "Pasada diaria omitida: ningún banco tiene sesión PSD2 — "
            f"no se ha escrito nada en las pestañas {result.raw_tab_name} y "
            f"{result.layout_tab_name} ({result.duration_seconds:.2f}s)",
            0,
        )

    if result.overall_status is OverallStatus.FULL_SUCCESS:
        headline = "Pasada diaria completada"
        exit_code = 0
    else:
        headline = "Pasada diaria parcial"
        exit_code = _PARTIAL_FAILURE_EXIT

    return (
        f"{headline}: {succeeded}/{total} bancos — "
        f"{result.total_rows_written} movimientos en la pestaña {result.raw_tab_name} y "
        f"{result.expense_count} filas en la pestaña {result.layout_tab_name} "
        f"({result.duration_seconds:.2f}s)",
        exit_code,
    )


def _total_failure_headline(exc: NoBankFetchedError) -> str:
    """The ``ERROR:`` line of the total-failure path, printed on stderr."""
    return f"ERROR: la pasada diaria falló — {exc}"


def _sheets_failure_headline(exc: DailySheetsError) -> str:
    """The ``ERROR (Sheets, etapa …):`` line, printed on stderr."""
    return f"ERROR (Sheets, etapa {exc.stage}): {exc}"


def _print_summary(
    result: DailySummary,
    notifier: EmailNotifier | None,
    summary_path: str | Path | None = None,
) -> int:
    """Print the run summary and per-bank report, notifying on partial failure."""
    succeeded = sum(1 for run in result.passes if _succeeded(run))
    total = len(result.passes)
    headline, exit_code = _completion_headline(result, succeeded, total)

    print(headline)

    _print_report(result.passes)
    outcomes = _as_outcomes(result.passes)
    print_not_onboarded_note(outcomes)

    if exit_code == _PARTIAL_FAILURE_EXIT:
        notification_exit = notify_and_exit(
            notifier,
            outcomes,
            sheets_error=None,
            tab_name=result.raw_tab_name,
            duration_seconds=result.duration_seconds,
            notifier_factory=EmailNotifier,
        )
        if notification_exit is not None:
            exit_code = notification_exit

    write_summary_file(
        summary_path,
        build_payload(result, headline=headline, exit_code=exit_code),
    )
    return exit_code


def _finish_total_failure(
    notifier: EmailNotifier | None,
    exc: NoBankFetchedError,
    summary_path: str | Path | None = None,
) -> int:
    """Print the total-failure error, notify, and return the exit code."""
    headline = _total_failure_headline(exc)
    print(headline, file=sys.stderr)
    notification_exit = notify_and_exit(
        notifier,
        _as_outcomes(exc.passes or []),
        sheets_error=None,
        tab_name=exc.raw_tab_name or current_tab_name(),
        duration_seconds=0.0,
        notifier_factory=EmailNotifier,
    )
    exit_code = notification_exit if notification_exit is not None else 1
    write_summary_file(
        summary_path,
        build_total_failure_payload(exc, headline=headline, exit_code=exit_code),
    )
    return exit_code


def _finish_sheets_failure(
    notifier: EmailNotifier | None,
    exc: DailySheetsError,
    summary_path: str | Path | None = None,
) -> int:
    """Print the Sheets error with its stage, notify, and return the exit code."""
    headline = _sheets_failure_headline(exc)
    print(headline, file=sys.stderr)
    notification_exit = notify_and_exit(
        notifier,
        _as_outcomes(exc.passes or []),
        sheets_error=f"etapa {exc.stage}: {exc}",
        tab_name=exc.tab_name or current_tab_name(),
        duration_seconds=0.0,
        notifier_factory=EmailNotifier,
    )
    exit_code = notification_exit if notification_exit is not None else 2
    write_summary_file(
        summary_path,
        build_sheets_failure_payload(exc, headline=headline, exit_code=exit_code),
    )
    return exit_code


def _as_outcomes(passes: Sequence[BankPass]) -> list[BankOutcome]:
    """Adapt daily results to the notifier's per-bank outcome type.

    A bank whose movements arrived is a success even when its balance stage
    failed, because a balance failure is not a run failure; the reason is still
    carried over so the email can name it.
    """
    outcomes: list[BankOutcome] = []
    for run in passes:
        succeeded = _succeeded(run)
        if not succeeded:
            failure_reason = (
                "sin sesión PSD2"
                if run.not_onboarded
                else run.transactions_failure or run.balance_failure or "unknown failure"
            )
        elif run.balance_failure is not None:
            failure_reason = f"{_BALANCE_FAILURE_REASON}: {run.balance_failure}"
        else:
            failure_reason = None
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
