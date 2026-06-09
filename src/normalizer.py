from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.logger import ProcessLogger


@dataclass(frozen=True)
class NormalizedTransaction:
    fecha: date
    importe: Decimal
    concepto: str
    banco: str


class DataNormalizer:
    """Transform raw Enable Banking API transaction payloads into NormalizedTransaction objects.

    Requirements: 3.1 (field mapping), 3.2 (Decimal precision), 3.3 (exclude invalid),
                  3.4 (concepto default), 3.5 (preserve sign).
    """

    def __init__(self, logger: Any = None) -> None:
        """
        Parameters
        ----------
        logger:
            Optional ProcessLogger instance. When provided, WARNING entries are
            written for each excluded transaction. If None, exclusions are silent.
        """
        self._logger = logger

    def normalize(
        self,
        raw_transactions: list[dict],
        bank: str,
    ) -> list[NormalizedTransaction]:
        """Normalize raw API transactions into validated NormalizedTransaction objects.

        Transactions missing any required field (fecha, importe, banco) are excluded
        and a WARNING is logged if a logger is available.

        Parameters
        ----------
        raw_transactions:
            List of raw transaction dicts returned by the Enable Banking API.
        bank:
            Name of the bank entity — used as the ``banco`` field.

        Returns
        -------
        list[NormalizedTransaction]
            Possibly empty list of valid normalized transactions.
        """
        result: list[NormalizedTransaction] = []

        for tx in raw_transactions:
            # --- fecha: prefer booking_date, fallback to value_date ---
            fecha = self._parse_date(tx.get("booking_date") or tx.get("value_date"))

            # --- importe: from transaction_amount.amount ---
            amount_block = tx.get("transaction_amount") or {}
            importe = self._parse_decimal(amount_block.get("amount"))

            # --- banco: always the passed-in bank argument ---
            # banco is required and always present (the bank parameter itself);
            # however, if bank is empty/None we treat it as missing.
            banco: str | None = bank if bank else None

            # --- exclude if any required field is absent ---
            if fecha is None or importe is None or not banco:
                if self._logger is not None:
                    self._logger.warning(
                        "DataNormalizer",
                        bank or None,
                        f"Transaction excluded: missing required field(s). Raw: {tx}",
                    )
                continue

            # --- concepto: use remittance_information, default to "" ---
            raw_concepto = tx.get("remittance_information")
            concepto: str = str(raw_concepto) if raw_concepto is not None else ""

            result.append(
                NormalizedTransaction(
                    fecha=fecha,
                    importe=importe,
                    concepto=concepto,
                    banco=banco,
                )
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        """Parse an ISO 8601 date string (YYYY-MM-DD) into a datetime.date.

        Returns None if the value is absent, None, or cannot be parsed.
        """
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_decimal(value: Any) -> Decimal | None:
        """Convert a string or numeric value to Decimal, preserving sign.

        Returns None if the value is absent, None, or cannot be converted.
        Never uses float arithmetic (Requirement 3.2).
        """
        if value is None:
            return None
        try:
            # Convert via str to avoid float representation issues
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return None
