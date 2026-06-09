"""
Custom exceptions for the Enable Banking API integration pipeline.

Security note (Requirement 7.3): no exception message may contain
credential values, token values, or any other sensitive secret.
Messages must identify *which* secret or resource is affected without
revealing its expected value.
"""


class BankAuthError(Exception):
    """Raised when authentication with a bank fails.

    Typical causes:
    - Refresh token is invalid or has expired.
    - The OAuth token endpoint rejects the request (HTTP 401 / 403).

    The message MUST identify the affected bank entity but MUST NOT
    include any credential value.

    Example::

        raise BankAuthError("ING: refresh token is invalid or expired")
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class BankAPIError(Exception):
    """Raised when the Enable Banking API returns an unrecoverable error.

    Typical causes:
    - HTTP 4xx (non-auth) or 5xx response after all retry attempts are
      exhausted.
    - Network-level failure that persists beyond the retry budget.

    The message MUST include the affected bank entity and the HTTP status
    code (if applicable) but MUST NOT include any credential value.

    Example::

        raise BankAPIError("Sabadell: API returned HTTP 503 after 5 retries")
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MissingSecretError(Exception):
    """Raised when a required secret or credential is absent or empty.

    Typical causes:
    - The environment variable for a token is not set in the Secret Store.
    - The environment variable exists but holds an empty string.

    The message MUST identify *which key* is missing but MUST NOT reveal
    the expected value of that key.

    Example::

        raise MissingSecretError("Required secret 'ING_ACCESS_TOKEN' is not set")
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ExcelWriteError(Exception):
    """Raised when persisting data to an Excel workbook fails.

    Typical causes:
    - An exception occurred mid-write, preventing a safe save-and-close.
    - The output directory is not writable.
    - `openpyxl` raises an internal error during serialisation.

    The workbook MUST NOT be saved when this exception is raised (the
    caller is responsible for not calling ``workbook.save()`` after the
    error).

    Example::

        raise ExcelWriteError("movimientos_2025_01.xlsx: write interrupted, file not saved")
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
