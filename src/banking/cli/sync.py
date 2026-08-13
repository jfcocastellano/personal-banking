"""CLI handler for the ``banking sync`` subcommand."""

from __future__ import annotations

import argparse
import sys

from banking.sync import AllBanksFailedError, OverallStatus, SheetsSyncError, run_sync


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``sync`` subcommand.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    subparsers.add_parser(
        "sync",
        help="Fetch this month's movements from all four banks and write them to Google Sheets",
    )


def handle(args: argparse.Namespace) -> int:
    """Run the sync pipeline and print a human-readable summary or error.

    Returns:
        Exit code: ``0`` on full success, ``1`` if all four banks failed,
        ``2`` if writing to Google Sheets failed, ``3`` on partial failure
        (at least one bank succeeded and at least one failed).
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
    return exit_code
