"""CLI handler for the ``banking sync`` subcommand."""

from __future__ import annotations

import argparse
import sys

from banking.sync import IngSyncError, SheetsSyncError, run_sync


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``sync`` subcommand.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    subparsers.add_parser(
        "sync",
        help="Fetch this month's ING movements and write them to Google Sheets",
    )


def handle(args: argparse.Namespace) -> int:
    """Run the sync pipeline and print a human-readable summary or error.

    Returns:
        Exit code: ``0`` on success, ``1`` if obtaining ING movements
        failed, ``2`` if writing to Google Sheets failed.
    """
    try:
        result = run_sync()
    except IngSyncError as exc:
        print(f"ERROR (ING): {exc}", file=sys.stderr)
        return 1
    except SheetsSyncError as exc:
        print(f"ERROR (Sheets): {exc}", file=sys.stderr)
        return 2

    print(
        f"Sincronización completada: {result.bank_name} — "
        f"{result.rows_written} movimientos escritos en la pestaña {result.tab_name} "
        f"({result.duration_seconds:.2f}s)"
    )
    return 0
