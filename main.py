"""
main.py — Orquestador del flujo de obtención y persistencia de movimientos bancarios.

Coordina los componentes TransactionFetcher, DataNormalizer y ExcelWriter para
las cuatro entidades bancarias configuradas. Captura errores por entidad de forma
aislada y devuelve un código de salida que refleja el resultado global del flujo.

Implements Requirements: 2.3, 2.5, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from src.excel_writer import ExcelWriter
from src.exceptions import BankAPIError, BankAuthError, ExcelWriteError, MissingSecretError
from src.fetcher import TransactionFetcher, get_yesterday
from src.logger import ProcessLogger
from src.normalizer import DataNormalizer
from src.secret_store import SecretStore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BANKS = ["ING", "Sabadell", "Revolut", "MyInvestor"]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the daily bank transaction fetch-and-persist flow.

    For each bank in BANKS:
      1. Instantiate a fresh TransactionFetcher (reads tokens from SecretStore).
      2. Fetch transactions for yesterday.
      3. Normalize the raw data.
      4. Write normalized transactions to the monthly Excel file.

    Any per-bank error is logged and the bank is skipped; the remaining banks
    are always processed (Requirements 2.3, 2.4).

    Returns
    -------
    int
        0 if all banks were processed successfully, 1 if any bank failed
        (Requirements 2.5, 6.3).
    """
    logger = ProcessLogger(log_dir=Path("logs"))
    secret_store = SecretStore()
    normalizer = DataNormalizer(logger=logger)
    writer = ExcelWriter(output_dir=Path("."))

    yesterday = get_yesterday(date.today())

    failed = False

    for bank in BANKS:
        try:
            fetcher = TransactionFetcher(bank=bank, secret_store=secret_store)
            raw = fetcher.fetch_transactions(yesterday, yesterday)
            normalized = normalizer.normalize(raw, bank)
            writer.write(normalized)
        except BankAuthError as exc:
            logger.error("main", bank, str(exc))
            failed = True
        except BankAPIError as exc:
            logger.error("main", bank, str(exc))
            failed = True
        except MissingSecretError as exc:
            logger.error("main", bank, str(exc))
            failed = True
        except ExcelWriteError as exc:
            logger.error("main", bank, str(exc))
            failed = True
        except Exception as exc:  # noqa: BLE001
            logger.error("main", bank, str(exc))
            failed = True

    # Log final flow outcome (Requirement 8.5)
    logger.info("main", None, f"Flujo finalizado: {'failure' if failed else 'success'}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
