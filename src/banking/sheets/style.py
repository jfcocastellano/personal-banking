"""Sheet styling taken from the owner's ledger workbook (task 022).

The reference is `Gastos 2026 hasta 31 octubre inclusive.xlsx`, sheet `Plantilla`: Arial,
row height 12.75, no borders, no banding, three vertical blocks each with its own accent,
body in Arial 12 bold, amounts as ``#,##0.00 _€``.

The payload is built by a pure function so the requests can be inspected before any of
them touches the document.
"""

from __future__ import annotations

from typing import Any

ARIAL = "Arial"
BODY_SIZE = 12
AMOUNT_FORMAT = "#,##0.00 _€"

RED = {"red": 1.0, "green": 0.0, "blue": 0.0}
GREEN = {"red": 0.34, "green": 0.82, "blue": 0.31}
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
    return requests


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
