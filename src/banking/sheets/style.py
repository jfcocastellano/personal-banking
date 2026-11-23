"""Sheet styling taken from the owner's ledger workbook (task 022).

The reference is `Gastos 2026 hasta 31 octubre inclusive.xlsx`, sheet `Plantilla`: Arial,
row height 12.75, no borders, no banding, three vertical blocks each with its own accent,
body in Arial 12 bold, amounts as ``#,##0.00 _€``.

The payload is built by a pure function so the requests can be inspected before any of
them touches the document.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from banking.sheets.layout import (
    _BALANCE_FIRST_ROW,
    _BALANCE_HEADER_ROW,
    _BALANCE_TITLE_ROW,
    _COL_J,
    _COL_K,
    _HEADER_ROW,
    _SUMMARY_FIRST_ROW,
    _SUMMARY_PANEL_LAST_ROW,
    _SUMMARY_TOTAL_ROW,
    _TITLE_ROW,
)

ARIAL = "Arial"
BODY_SIZE = 12
AMOUNT_FORMAT = "#,##0.00 _€"

RED = {"red": 1.0, "green": 0.0, "blue": 0.0}
GREEN = {"red": 0.34, "green": 0.82, "blue": 0.31}
BLUE = {"red": 0.33, "green": 0.55, "blue": 0.83}
ORANGE = {"red": 0.98, "green": 0.75, "blue": 0.56}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}

_ROW_HEIGHT = 12.75


def _cell_format(
    *,
    background: dict[str, float] | None = None,
    bold: bool = False,
    color: dict[str, float] | None = None,
    halign: str | None = None,
    number_format: str | None = None,
) -> dict[str, Any]:
    """One ``userEnteredFormat``, with only the properties that were asked for."""
    text: dict[str, Any] = {"fontFamily": ARIAL, "fontSize": BODY_SIZE, "bold": bold}
    if color is not None:
        text["foregroundColor"] = color
    fmt: dict[str, Any] = {"textFormat": text}
    if background is not None:
        fmt["backgroundColor"] = background
    if halign is not None:
        fmt["horizontalAlignment"] = halign
    if number_format is not None:
        fmt["numberFormat"] = {"type": "NUMBER", "pattern": number_format}
    return fmt


def _repeat(
    sheet_id: int, start_row: int, end_row: int, start_col: int, end_col: int, fmt: dict[str, Any]
) -> dict[str, Any]:
    """A ``repeatCell`` over a half-open grid range, touching format only."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": start_row - 1,
                "endRowIndex": end_row,
                "startColumnIndex": start_col - 1,
                "endColumnIndex": end_col,
            },
            "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat(" + ",".join(sorted(fmt)) + ")",
        }
    }


def _block(
    sheet_id: int,
    *,
    accent: dict[str, float],
    title_row: int,
    header_row: int,
    first_row: int,
    last_row: int,
    first_col: int,
    last_col: int,
) -> list[dict[str, Any]]:
    """Title band, header band and body for one block, in the reference's style."""
    return [
        _repeat(
            sheet_id,
            title_row,
            title_row,
            first_col,
            last_col,
            _cell_format(background=accent, bold=True, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            header_row,
            header_row,
            first_col,
            last_col,
            _cell_format(background=accent, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(sheet_id, first_row, last_row, first_col, last_col, _cell_format(bold=True)),
    ]


def format_requests(sheet_id: int) -> list[dict[str, Any]]:
    """Requests that paint the month tab the way the ledger workbook looks.

    Covers the two columns blocks whose geometry is fixed by ``layout.py``: expenses
    (``B:E``, rows 2-403) and shared expenses (``G:H``, rows 2-53). The summary and
    balance blocks in ``J:K`` are left alone on purpose — their cell positions depend on
    what the owner has filled in, and a guessed range would repaint his own formatting.
    """
    requests = _block(
        sheet_id,
        accent=RED,
        title_row=2,
        header_row=3,
        first_row=4,
        last_row=403,
        first_col=2,
        last_col=5,
    )
    # Importes: the reference centres them and gives them its own number pattern.
    requests.append(
        _repeat(
            sheet_id,
            4,
            403,
            5,
            5,
            _cell_format(bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        )
    )
    requests.extend(
        _block(
            sheet_id,
            accent=GREEN,
            title_row=2,
            header_row=3,
            first_row=4,
            last_row=53,
            first_col=7,
            last_col=8,
        )
    )
    requests.append(
        _repeat(
            sheet_id,
            4,
            53,
            8,
            8,
            _cell_format(bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        )
    )
    requests.extend(_right_hand_panel(sheet_id))
    return requests


def _right_hand_panel(sheet_id: int) -> list[dict[str, Any]]:
    """The ``J:K`` column: income band, month summary and account balances.

    Row and column boundaries come from ``layout.py`` so the bands follow what the
    writer owns. Those constants are 0-based; ``_repeat`` takes 1-based columns.
    """
    j, k = _COL_J + 1, _COL_K + 1
    return [
        _repeat(
            sheet_id,
            _TITLE_ROW,
            _TITLE_ROW,
            j,
            k,
            _cell_format(background=GREEN, bold=True, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _HEADER_ROW,
            _HEADER_ROW,
            j,
            k,
            _cell_format(background=GREEN, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _SUMMARY_FIRST_ROW,
            _SUMMARY_TOTAL_ROW,
            j,
            k,
            _cell_format(background=BLUE, bold=True),
        ),
        _repeat(
            sheet_id,
            _SUMMARY_FIRST_ROW,
            _SUMMARY_TOTAL_ROW,
            k,
            k,
            _cell_format(background=BLUE, bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        ),
        _repeat(
            sheet_id,
            _BALANCE_TITLE_ROW,
            _BALANCE_TITLE_ROW,
            j,
            k,
            _cell_format(background=ORANGE, bold=True, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _BALANCE_HEADER_ROW,
            _BALANCE_HEADER_ROW,
            j,
            k,
            _cell_format(background=ORANGE, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id, _BALANCE_FIRST_ROW, _SUMMARY_PANEL_LAST_ROW, j, k, _cell_format(bold=True)
        ),
        _repeat(
            sheet_id,
            _BALANCE_FIRST_ROW,
            _SUMMARY_PANEL_LAST_ROW,
            k,
            k,
            _cell_format(bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        ),
    ]


def row_height_requests(sheet_id: int, rows: int) -> list[dict[str, Any]]:
    """The reference's uniform 12.75 pt row height."""
    return [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": rows,
                },
                "properties": {"pixelSize": 17},
                "fields": "pixelSize",
            }
        }
    ]


def indent_requests(
    sheet_id: int, rows: Sequence[int], column: int, points: float = 12.0
) -> list[dict[str, Any]]:
    """Indent single-column cells, like the ledger's tabulated sub-items."""
    fmt: dict[str, Any] = {"padding": {"left": points}}
    return [_repeat(sheet_id, row, row, column, column, fmt) for row in rows]
