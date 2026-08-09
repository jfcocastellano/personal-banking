"""Generic Google Sheets writer: service-account auth, create/overwrite a tab."""

import json
import logging
import time

import gspread

from banking.config.secret_store import ConfigurationError, DecryptionError, SecretStore

logger = logging.getLogger(__name__)

_SECRET_KEY = "GOOGLE_SHEETS_CREDENTIALS"

CellValue = str | int | float | bool | None


class SheetsConfigError(Exception):
    """Raised when the service account credentials are missing or invalid."""


class SheetsAccessError(Exception):
    """Raised when the target document is inaccessible (missing or unshared)."""


class SheetsQuotaExceededError(Exception):
    """Raised when the Google Sheets API reports the request quota exceeded."""


class SheetsAPIError(Exception):
    """Raised on any other unexpected Google Sheets API error."""


def _build_client() -> gspread.Client:
    """Build a gspread client from the service account JSON in the SecretStore.

    Raises:
        SheetsConfigError: if the secret is missing, not valid JSON, or
            rejected by gspread/google-auth while authenticating.
    """
    try:
        raw = SecretStore().get(_SECRET_KEY)
    except (KeyError, ConfigurationError, DecryptionError) as exc:
        raise SheetsConfigError(f"'{_SECRET_KEY}' is not available from the SecretStore.") from exc

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SheetsConfigError(f"'{_SECRET_KEY}' does not contain valid JSON.") from exc

    try:
        return gspread.service_account_from_dict(info)
    except Exception as exc:
        raise SheetsConfigError(
            f"'{_SECRET_KEY}' was rejected while authenticating with Google Sheets."
        ) from exc


def _translate_api_error(exc: gspread.exceptions.APIError) -> Exception:
    """Map a gspread APIError to the appropriate component exception."""
    status_code = exc.response.status_code
    if status_code in (403, 404):
        return SheetsAccessError(f"Google Sheets API denied access (HTTP {status_code}).")
    if status_code == 429:
        return SheetsQuotaExceededError("Google Sheets API request quota exceeded (HTTP 429).")
    return SheetsAPIError(f"Unexpected Google Sheets API error (HTTP {status_code}).")


def _open_spreadsheet(client: gspread.Client, document_id: str) -> gspread.Spreadsheet:
    """Open the target spreadsheet, translating access/quota/API failures."""
    try:
        return client.open_by_key(document_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise SheetsAccessError(
            f"Document '{document_id}' does not exist or is not shared with the service account."
        ) from exc
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _prepare_worksheet(
    spreadsheet: gspread.Spreadsheet, tab_name: str, headers: list[CellValue]
) -> gspread.Worksheet:
    """Resolve the target worksheet: create it if missing, clear it if it exists."""
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        try:
            return spreadsheet.add_worksheet(title=tab_name, rows=1, cols=max(len(headers), 1))
        except gspread.exceptions.APIError as exc:
            raise _translate_api_error(exc) from exc
    worksheet.clear()
    return worksheet


class SheetsWriter:
    """Writes generic tabular data to a Google Sheets tab, creating or
    overwriting it as needed. Has no knowledge of any banking concepts.
    """

    def __init__(self, client: gspread.Client | None = None) -> None:
        self._client = client

    def write(
        self,
        document_id: str,
        tab_name: str,
        headers: list[CellValue],
        rows: list[list[CellValue]],
    ) -> None:
        """Create or overwrite *tab_name* in *document_id* with headers+rows.

        Raises:
            SheetsConfigError: invalid/missing service account credentials.
            SheetsAccessError: document or tab inaccessible.
            SheetsQuotaExceededError: Google Sheets API quota exceeded.
            SheetsAPIError: any other unexpected API error.
        """
        start = time.monotonic()
        try:
            client = self._client or _build_client()
            spreadsheet = _open_spreadsheet(client, document_id)
            worksheet = _prepare_worksheet(spreadsheet, tab_name, headers)
            try:
                worksheet.update(values=[headers, *rows])
            except gspread.exceptions.APIError as exc:
                raise _translate_api_error(exc) from exc
        except (
            SheetsConfigError,
            SheetsAccessError,
            SheetsQuotaExceededError,
            SheetsAPIError,
        ) as exc:
            logger.error(
                "Sheets write failed: tab=%s category=%s reason=%s",
                tab_name,
                type(exc).__name__,
                exc,
            )
            raise

        duration = time.monotonic() - start
        logger.info(
            "Sheets write succeeded: tab=%s rows_written=%d duration=%.3fs",
            tab_name,
            len(rows),
            duration,
        )
