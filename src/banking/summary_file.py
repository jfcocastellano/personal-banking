"""The JSON run summary that ``banking daily --summary-json`` writes.

The scheduled workflow publishes a run summary on the execution page. Scraping
that summary from the command's log prose coupled the workflow to log format
strings, so ``banking daily`` can now write one JSON document with both the
structured values and the exact headline the process printed.

The document is a presentation detail of the daily pass: it never changes what
``banking daily`` prints, what it writes to Sheets or which exit code it
returns. A file that cannot be written only produces one warning on stderr,
because the scheduled run must still fail (or succeed) for its own reasons.

``status`` is the lowercased `banking.sync.OverallStatus` for a completed run,
and ``total_failure`` / ``sheets_failure`` for the two failure paths, which
carry ``exit_code`` as the FINAL code of the run, including ``4`` when the
failure email could not be delivered.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from banking.daily import (
    BankPass,
    DailySheetsError,
    DailySummary,
    NoBankFetchedError,
    _failed,
    _succeeded,
)
from banking.sheets.layout import layout_tab_name

#: Versioned identifier of the document shape, so a consumer can refuse a
#: document it does not understand.
SCHEMA = "banking.summary/v1"

#: Status of a run that raised `banking.daily.NoBankFetchedError`.
TOTAL_FAILURE_STATUS = "total_failure"

#: Status of a run that raised `banking.daily.DailySheetsError`.
SHEETS_FAILURE_STATUS = "sheets_failure"

#: Prefix of the single stderr line a failed write degrades to.
WRITE_WARNING = "AVISO: no se pudo escribir el resumen JSON"


def _execution_date(today: date | None) -> date:
    """The run's execution date: injected by tests, today in production."""
    return today if today is not None else date.today()


def _month_tab(execution_date: date) -> str:
    """The raw tab of the execution month, ``<YYYY-MM>``."""
    return execution_date.strftime("%Y-%m")


def _layout_tab(execution_date: date) -> str:
    """The layout tab of the execution month, ``<YYYY-MM> Gastos``."""
    return layout_tab_name(execution_date.replace(day=1))


def _bank_entry(run: BankPass) -> dict[str, object]:
    """One per-bank entry: what the bank returned and how each stage ended."""
    return {
        "bank": run.bank_name,
        "not_onboarded": run.not_onboarded,
        "transactions": len(run.transactions),
        "balance_reported": run.balance is not None,
        "transactions_failure": run.transactions_failure,
        "balance_failure": run.balance_failure,
    }


def _payload(
    *,
    execution_date: date,
    status: str,
    exit_code: int,
    headline: str,
    raw_tab: str,
    layout_tab: str,
    passes: Sequence[BankPass],
    rows_written: int,
    expense_count: int,
    balance_count: int,
    duration_seconds: float,
    sheets_error: str | None,
) -> dict[str, object]:
    """Assemble the document, deriving the per-bank aggregates from ``passes``."""
    return {
        "schema": SCHEMA,
        "date": execution_date.isoformat(),
        "status": status,
        "exit_code": exit_code,
        "raw_tab": raw_tab,
        "layout_tab": layout_tab,
        "headline": headline,
        "banks_total": len(passes),
        "banks_succeeded": sum(1 for run in passes if _succeeded(run)),
        "banks_not_onboarded": sum(1 for run in passes if run.not_onboarded),
        "banks_failed": sum(1 for run in passes if _failed(run)),
        "balance_failures": sum(1 for run in passes if run.balance_failure is not None),
        "rows_written": rows_written,
        "expense_count": expense_count,
        "balance_count": balance_count,
        "duration_seconds": duration_seconds,
        "sheets_error": sheets_error,
        "not_onboarded_banks": [run.bank_name for run in passes if run.not_onboarded],
        "banks": [_bank_entry(run) for run in passes],
    }


def build_payload(
    summary: DailySummary,
    *,
    headline: str,
    exit_code: int,
    today: date | None = None,
) -> dict[str, object]:
    """Build the document of a completed run (success or nothing to sync).

    Args:
        summary: The aggregate outcome of the daily pass.
        headline: The exact summary line the command printed on stdout.
        exit_code: The final exit code of the run.
        today: The execution date. Defaults to `datetime.date.today`.

    Returns:
        The payload, ready for `write_summary_file`.
    """
    return _payload(
        execution_date=_execution_date(today),
        status=summary.overall_status.value,
        exit_code=exit_code,
        headline=headline,
        raw_tab=summary.raw_tab_name,
        layout_tab=summary.layout_tab_name,
        passes=summary.passes,
        rows_written=summary.total_rows_written,
        expense_count=summary.expense_count,
        balance_count=summary.balance_count,
        duration_seconds=summary.duration_seconds,
        sheets_error=None,
    )


def build_total_failure_payload(
    exc: NoBankFetchedError,
    *,
    headline: str,
    exit_code: int,
    today: date | None = None,
) -> dict[str, object]:
    """Build the document of a run where no bank could contribute movements.

    Nothing was written, so every counter is ``0`` and ``duration_seconds`` is
    ``0.0``: the exception carries no duration, and the command already reports
    ``0.0`` to the notifier on this path.
    """
    execution_date = _execution_date(today)
    return _payload(
        execution_date=execution_date,
        status=TOTAL_FAILURE_STATUS,
        exit_code=exit_code,
        headline=headline,
        raw_tab=exc.raw_tab_name or _month_tab(execution_date),
        layout_tab=exc.layout_tab_name or _layout_tab(execution_date),
        passes=exc.passes or [],
        rows_written=0,
        expense_count=0,
        balance_count=0,
        duration_seconds=0.0,
        sheets_error=None,
    )


def build_sheets_failure_payload(
    exc: DailySheetsError,
    *,
    headline: str,
    exit_code: int,
    today: date | None = None,
) -> dict[str, object]:
    """Build the document of a run whose raw or layout write failed.

    Only the failed stage names its tab: the exception carries the tab it could
    not write, and a layout-stage failure carries ``"<YYYY-MM> Gastos"``
    (``banking.daily`` raises it with ``tab_name=target_layout_tab``), so the
    other tab always keeps the month's own name.

    A raw failure left both tabs untouched, so no counter moves. A layout
    failure happened after the raw tab was written: ``rows_written`` therefore
    reports what that stage did write, while the layout counters stay ``0``
    because the layout tab was never filled.
    """
    execution_date = _execution_date(today)
    month_tab = _month_tab(execution_date)
    month_layout_tab = _layout_tab(execution_date)
    passes = exc.passes or []
    raw_failed = exc.stage == "raw"
    return _payload(
        execution_date=execution_date,
        status=SHEETS_FAILURE_STATUS,
        exit_code=exit_code,
        headline=headline,
        raw_tab=(exc.tab_name or month_tab) if raw_failed else month_tab,
        layout_tab=month_layout_tab if raw_failed else (exc.tab_name or month_layout_tab),
        passes=passes,
        rows_written=0 if raw_failed else sum(len(run.transactions) for run in passes),
        expense_count=0,
        balance_count=0,
        duration_seconds=0.0,
        sheets_error=f"etapa {exc.stage}: {exc}",
    )


def _remove_quietly(path: Path) -> None:
    """Drop the sibling temp file a failed write may have left behind."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def write_summary_file(path: str | Path | None, payload: Mapping[str, object]) -> None:
    """Write ``payload`` to ``path`` atomically, warning instead of failing.

    The document is rendered first and then moved into place with `os.replace`,
    so a consumer never reads a half-written file.

    Args:
        path: Destination path, or ``None`` when the flag was absent, in which
            case nothing is written.
        payload: The document to write, normally from `build_payload`.
    """
    if path is None:
        return

    target = Path(path)
    document = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(document, encoding="utf-8")
        os.replace(temporary, target)
    except OSError as exc:
        _remove_quietly(temporary)
        print(f"{WRITE_WARNING} en {target}: {exc}", file=sys.stderr)
