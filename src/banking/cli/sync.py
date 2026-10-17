"""CLI handler for the ``banking sync`` subcommand."""

from __future__ import annotations

import argparse
import sys

from banking.notify import DeliveryStatus, EmailNotifier
from banking.sync import AllBanksFailedError, BankOutcome, OverallStatus, SheetsSyncError, run_sync

_NOTIFICATION_FAILED_MESSAGE = "ERROR (notificación): no se pudo enviar el email de aviso"


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
        Exit code: ``0`` on full success, ``1`` if all four banks failed,
        ``2`` if writing to Google Sheets failed, ``3`` on partial failure
        (at least one bank succeeded and at least one failed), ``4`` if the
        failure notification could not be delivered.
    """
    try:
        result = run_sync()
    except AllBanksFailedError as exc:
        print(
            "ERROR: los 4 bancos fallaron — no se ha escrito nada en Google Sheets",
            file=sys.stderr,
        )
        print(f"  {exc}", file=sys.stderr)
        return 1
    except SheetsSyncError as exc:
        print(f"ERROR (Sheets): {exc}", file=sys.stderr)
        return 2

    succeeded = sum(1 for outcome in result.outcomes if outcome.succeeded)
    total = len(result.outcomes)

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
        else:
            print(f"  - {outcome.bank_name}: FALLÓ — {outcome.failure_reason}")

    if exit_code == 3:
        notification_exit = _notify_and_exit(
            notifier,
            outcomes=result.outcomes,
            sheets_error=None,
            tab_name=result.tab_name,
            duration_seconds=result.duration_seconds,
        )
        if notification_exit is not None:
            return notification_exit
    return exit_code


def _notify_and_exit(
    notifier: EmailNotifier | None,
    outcomes: list[BankOutcome],
    sheets_error: str | None,
    tab_name: str,
    duration_seconds: float,
) -> int | None:
    """Send the failure email and translate a delivery failure into exit code 4.

    Returns:
        ``4`` when the delivery failed, ``None`` when it was sent or skipped
        (in which case the caller keeps the sync outcome's exit code).
    """
    email_notifier = notifier if notifier is not None else EmailNotifier()
    status = email_notifier.notify_failure(
        outcomes=outcomes,
        sheets_error=sheets_error,
        tab_name=tab_name,
        duration_seconds=duration_seconds,
    )
    if status is DeliveryStatus.FAILED:
        print(_NOTIFICATION_FAILED_MESSAGE, file=sys.stderr)
        return 4
    return None
