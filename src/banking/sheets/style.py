"""Sheet styling taken from the owner's ledger workbook (task 022).

The reference is `Gastos 2026 hasta 31 octubre inclusive.xlsx`, sheet `Plantilla`: Arial,
row height 12.75, no borders, no banding, three vertical blocks each with its own accent,
body in Arial 12 bold, amounts as ``#,##0.00 _€``.

The payload is built by a pure function so the requests can be inspected before any of
them touches the document.
"""

from __future__ import annotations

from typing import Any

from banking.sheets.layout import (
    _BALANCE_FIRST_ROW,
    _BALANCE_HEADER_ROW,
    _BALANCE_TITLE_ROW,
    _COL_J,
    _COL_K,
    _INCOME_FIRST_ROW,
    _INCOME_HEADER_ROW,
    _INCOME_LAST_ROW,
    _INCOME_TITLE_ROW,
    _SUMMARY_HEADER_ROW,
    _SUMMARY_INCOME_ROW,
    _SUMMARY_PANEL_LAST_ROW,
    _SUMMARY_TITLE_ROW,
    _SUMMARY_TOTAL_ROW,
)

ARIAL = "Arial"
BODY_SIZE = 12
AMOUNT_FORMAT = "#,##0.00 _€"

RED = {"red": 1.0, "green": 0.0, "blue": 0.0}
ORANGE = {"red": 0.98, "green": 0.75, "blue": 0.56}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}

# Right-hand panel, taken from the capture the owner sent (task 022): each block is a
# dark title band with white letters over a lighter header band, one hue per block.
GREEN_TITLE = {"red": 0.61, "green": 0.73, "blue": 0.35}  # 9BBB59
GREEN_HEADER = {"red": 0.57, "green": 0.82, "blue": 0.31}  # 92D050
BLUE_TITLE = {"red": 0.31, "green": 0.51, "blue": 0.74}  # 4F81BD
BLUE_HEADER = {"red": 0.33, "green": 0.55, "blue": 0.83}  # 548DD4
SALMON_TITLE = {"red": 0.75, "green": 0.31, "blue": 0.30}  # C0504D
SALMON_HEADER = {"red": 0.98, "green": 0.75, "blue": 0.56}  # FABF8F

# Every row is the same height: the owner picked a real row (2026-11-05, ``DELICIES
# ALBAL``) that happened to carry the header height and asked for the whole sheet to
# look like that. 28 px over the reference's 17 keeps the bold labels from looking
# cramped.
_ROW_HEIGHT = 28
# Column widths are not set here: ``layout.content_width_requests`` measures the
# widest rendered cell in each column, hand-typed content included.


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

    Covers every block whose geometry is fixed by ``layout.py``: expenses (``B:E``,
    rows 2-403), shared expenses (``G:H``, rows 2-53) and the right-hand panel
    (``J:K``, income table, month summary and balances). The income amounts in
    ``K4:K10`` are typed by hand, so the panel only paints them; it never writes
    a value there.
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
            accent=ORANGE,
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
    """The ``J:K`` column: income table, month summary and account balances.

    Row and column boundaries come from ``layout.py`` so the bands follow what the
    writer owns. Those constants are 0-based; ``_repeat`` takes 1-based columns.
    """
    j, k = _COL_J + 1, _COL_K + 1
    return [
        # INGRESOS: the income table, green.
        _repeat(
            sheet_id,
            _INCOME_TITLE_ROW,
            _INCOME_TITLE_ROW,
            j,
            k,
            _cell_format(background=GREEN_TITLE, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _INCOME_HEADER_ROW,
            _INCOME_HEADER_ROW,
            j,
            k,
            _cell_format(background=GREEN_HEADER, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _INCOME_FIRST_ROW,
            _INCOME_LAST_ROW,
            j,
            k,
            _cell_format(background=WHITE, bold=True),
        ),
        _repeat(
            sheet_id,
            _INCOME_FIRST_ROW,
            _INCOME_LAST_ROW,
            k,
            k,
            _cell_format(background=WHITE, bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        ),
        # RESUMEN MES: blue, the month summary the owner checks at a glance.
        _repeat(
            sheet_id,
            _SUMMARY_TITLE_ROW,
            _SUMMARY_TITLE_ROW,
            j,
            k,
            _cell_format(background=BLUE_TITLE, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _SUMMARY_HEADER_ROW,
            _SUMMARY_HEADER_ROW,
            j,
            k,
            _cell_format(background=BLUE_HEADER, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _SUMMARY_INCOME_ROW,
            _SUMMARY_TOTAL_ROW,
            j,
            k,
            _cell_format(background=WHITE, bold=True),
        ),
        _repeat(
            sheet_id,
            _SUMMARY_INCOME_ROW,
            _SUMMARY_TOTAL_ROW,
            k,
            k,
            _cell_format(background=WHITE, bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        ),
        _repeat(
            sheet_id,
            _BALANCE_TITLE_ROW,
            _BALANCE_TITLE_ROW,
            j,
            k,
            _cell_format(background=SALMON_TITLE, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _BALANCE_HEADER_ROW,
            _BALANCE_HEADER_ROW,
            j,
            k,
            _cell_format(background=SALMON_HEADER, bold=True, color=WHITE, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _BALANCE_FIRST_ROW,
            _SUMMARY_PANEL_LAST_ROW,
            j,
            k,
            _cell_format(background=WHITE, bold=True, halign="CENTER"),
        ),
        _repeat(
            sheet_id,
            _BALANCE_FIRST_ROW,
            _SUMMARY_PANEL_LAST_ROW,
            k,
            k,
            _cell_format(background=WHITE, bold=True, halign="CENTER", number_format=AMOUNT_FORMAT),
        ),
    ]


def row_height_requests(sheet_id: int, rows: int) -> list[dict[str, Any]]:
    """One uniform row height for the whole tab, title and header rows included."""
    return [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": rows,
                },
                "properties": {"pixelSize": _ROW_HEIGHT},
                "fields": "pixelSize",
            }
        }
    ]


def layout_requests(sheet_id: int, *, column_count: int) -> list[dict[str, Any]]:
    """Structural touches that are not pure cell formatting.

    Merges the two ``J:K`` title bands that sit below the header, so they centre
    across both columns like the income title, and leaves one empty column on the far
    right. The trailing column is only inserted while the sheet still ends at ``K``,
    so running this twice does not keep appending columns.
    """
    j, k = _COL_J + 1, _COL_K + 1
    requests: list[dict[str, Any]] = []
    for title_row, accent in (
        (_SUMMARY_TITLE_ROW, BLUE_TITLE),
        (_BALANCE_TITLE_ROW, SALMON_TITLE),
    ):
        requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": title_row - 1,
                        "endRowIndex": title_row,
                        "startColumnIndex": _COL_J,
                        "endColumnIndex": _COL_K + 1,
                    },
                    "mergeType": "MERGE_ROWS",
                }
            }
        )
        requests.append(
            _repeat(
                sheet_id,
                title_row,
                title_row,
                j,
                k,
                _cell_format(background=accent, bold=True, color=WHITE, halign="CENTER"),
            )
        )
    if column_count <= _COL_K + 1:
        requests.append(
            {
                "appendDimension": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "length": 1,
                }
            }
        )
    return requests
