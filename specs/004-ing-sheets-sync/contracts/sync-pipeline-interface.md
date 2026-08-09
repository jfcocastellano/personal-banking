# Contrato: Interfaz Python del Pipeline de Sincronización

**Funcionalidad**: Pipeline de Sincronización ING → Google Sheets (IT4)
**Tipo**: Interfaz Python interna (consumida por `cli/sync.py`, y por un
futuro orquestador multi-banco, IT5+)
**Fecha**: 2026-08-09

---

## Módulo

`src/banking/sync.py`

---

## Función pública: `run_sync`

```python
def run_sync(
    connector: IngConnector | None = None,
    writer: SheetsWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> SyncResult: ...
```

**Parámetros** (todos opcionales, mismo patrón de inyección que
`IngConnector`/`SheetsWriter`):
- `connector`: si se omite, se construye `IngConnector()` real. Los tests
  **siempre** inyectan `Mock(spec=IngConnector)` (FR-010).
- `writer`: si se omite, se construye `SheetsWriter()` real. Los tests
  **siempre** inyectan `Mock(spec=SheetsWriter)` (FR-010).
- `document_id`: si se omite, se lee de
  `SecretStore().get("GOOGLE_SHEET_ID")`. Los tests inyectan un valor de
  prueba directamente, sin preparar un `SecretStore` cifrado.
- `today`: si se omite, se usa `date.today()`. Los tests inyectan una
  fecha fija para que el rango y el nombre de pestaña sean deterministas.

**Salida (éxito)**: `SyncResult` (ver `data-model.md` → Entidad 3).

**Salida (fallo)**: no retorna; lanza `IngSyncError` o `SheetsSyncError`
(ver `data-model.md` → Entidad 4). Nunca lanza una excepción de
`IngConnector`/`SheetsWriter` sin envolver.

**Efecto secundario**: exactamente un log estructurado por invocación
(`INFO` en éxito, `ERROR` en fallo — ver `research.md`, Decisión 7). Nunca
llama a `print()`.

---

## Constante pública añadida a `IngConnector` (extensión mínima de IT2)

```python
class IngConnector:
    BANK_NAME: str = _BANK_NAME  # "ING España"
```

---

## Ejemplo de uso (referencia, no es código de test)

```python
from banking.sync import run_sync, IngSyncError, SheetsSyncError

try:
    result = run_sync()
    print(f"{result.bank_name}: {result.rows_written} filas en {result.tab_name}")
except IngSyncError as exc:
    print(f"Fallo de ING: {exc}")
except SheetsSyncError as exc:
    print(f"Fallo de Sheets: {exc}")
```

## Ejemplo de test (referencia, no reemplaza `tasks.md`)

```python
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from banking.connectors.ing import IngConnector, Transaction
from banking.sheets.writer import SheetsWriter
from banking.sync import run_sync


def test_run_sync_transforms_and_writes() -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = [
        Transaction(date(2026, 8, 1), Decimal("42.50"), "EUR", "Nómina"),
    ]
    writer = Mock(spec=SheetsWriter)

    result = run_sync(
        connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    connector.fetch_transactions.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 15))
    writer.write.assert_called_once()
    assert result.tab_name == "2026-08"
    assert result.rows_written == 1
```

---

## Errores expuestos (importables desde `banking.sync`)

- `IngSyncError`
- `SheetsSyncError`

Ver `data-model.md` → Entidad 4 para cuándo se lanza cada una y su
código de salida asociado en la capa CLI.
