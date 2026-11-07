"""CLI handler for the ``banking sync`` subcommand."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from banking.cli.common import current_tab_name, notify_and_exit, print_not_onboarded_note
from banking.notify import EmailNotifier
from banking.sync import AllBanksFailedError, BankOutcome, OverallStatus, SheetsSyncError, run_sync


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``sync`` subcommand.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    subparsers.add_parser(
        "sync",
        help="Fetch this month's movements from all four banks and write them to Google Sheets",
    )


def handle(args: argparse.Namespace, notifier: EmailNotifier | None = None) -> int:
    """Run the sync pipeline and print a human-readable summary or error.

    Args:
        args: Parsed CLI arguments (the ``sync`` subcommand takes none).
        notifier: Email notifier to use for failures. Injected by tests; a real
            one is built only when a failure actually has to be notified.

    Returns:
        Exit code: ``0`` on full success (including runs where some banks have no
        PSD2 session yet: that is a normal state, not a failure, and including a
        run where no bank is onboarded at all, which writes nothing), ``1`` if
        every bank that had to sync failed, ``2`` if writing to Google Sheets
        failed, ``3`` on partial failure (at least one bank succeeded and at least
        one failed for real), ``4`` if the failure notification could not be
        delivered.
    """
    try:
        result = run_sync()
    except AllBanksFailedError as exc:
        return _finish_total_failure(notifier, exc)
    except SheetsSyncError as exc:
        return _finish_sheets_failure(notifier, exc)

    succeeded = sum(1 for outcome in result.outcomes if outcome.succeeded)
    total = len(result.outcomes)

    if result.overall_status is OverallStatus.NOTHING_TO_SYNC:
        # Nothing failed and nothing was written: say so, rather than reporting a
        # "completed" run with zero rows.
        exit_code = 0
        print(
            "Sincronización omitida: ningún banco tiene sesión PSD2 — "
            f"no se ha escrito nada en la pestaña {result.tab_name} "
            f"({result.duration_seconds:.2f}s)"
        )
    else:
        if result.overall_status == OverallStatus.FULL_SUCCESS:
            headline = "Sincronización completada"
            exit_code = 0
        else:
            headline = "Sincronización parcial"
            exit_code = 3

        print(
            f"{headline}: {succeeded}/{total} bancos — "
            f"{result.total_rows_written} movimientos escritos en la pestaña {result.tab_name} "
            f"({result.duration_seconds:.2f}s)"
        )
    for outcome in result.outcomes:
        if outcome.succeeded:
            print(f"  - {outcome.bank_name}: {outcome.rows_written} movimientos")
        elif outcome.not_onboarded:
            print(f"  - {outcome.bank_name}: SIN SESIÓN PSD2 — {outcome.failure_reason}")
        else:
            print(f"  - {outcome.bank_name}: FALLÓ — {outcome.failure_reason}")

    print_not_onboarded_note(result.outcomes)

    if exit_code == 3:
        notification_exit = notify_and_exit(
            notifier,
            result.outcomes,
            sheets_error=None,
            tab_name=result.tab_name,
            duration_seconds=result.duration_seconds,
            notifier_factory=EmailNotifier,
        )
        if notification_exit is not None:
            return notification_exit
    return exit_code


def _total_failure_headline(outcomes: Sequence[BankOutcome]) -> str:
    """Build the total-failure headline without claiming that every bank failed."""
    failed = [o for o in outcomes if o.failed]
    not_onboarded = [o for o in outcomes if o.not_onboarded]
    no_write = "no se ha escrito nada en Google Sheets"
    if not outcomes:
        return f"ERROR: ningún banco pudo sincronizar — {no_write}"
    if not not_onboarded:
        return f"ERROR: los {len(outcomes)} bancos fallaron — {no_write}"
    return (
        f"ERROR: {len(failed)} de {len(outcomes)} bancos fallaron, "
        f"{len(not_onboarded)} sin sesión PSD2 — {no_write}"
    )


def _finish_total_failure(notifier: EmailNotifier | None, exc: AllBanksFailedError) -> int:
    """Print the IT5 error for a total failure, notify, and return the exit code."""
    print(_total_failure_headline(exc.outcomes or []), file=sys.stderr)
    print(f"  {exc}", file=sys.stderr)
    notification_exit = notify_and_exit(
        notifier,
        exc.outcomes or [],
        sheets_error=None,
        tab_name=exc.tab_name or current_tab_name(),
        duration_seconds=0.0,
        notifier_factory=EmailNotifier,
    )
    return notification_exit if notification_exit is not None else 1


def _finish_sheets_failure(notifier: EmailNotifier | None, exc: SheetsSyncError) -> int:
    """Print the IT5 error for a Sheets failure, notify, and return the exit code."""
    print(f"ERROR (Sheets): {exc}", file=sys.stderr)
    notification_exit = notify_and_exit(
        notifier,
        exc.outcomes or [],
        sheets_error=str(exc),
        tab_name=exc.tab_name or current_tab_name(),
        duration_seconds=0.0,
        notifier_factory=EmailNotifier,
    )
    return notification_exit if notification_exit is not None else 2
