# Contrato: Interfaz Pública del Conector ING

**Funcionalidad**: Conector de Movimientos ING España (Enable Banking) (IT2)
**Tipo**: Interfaz Python interna (consumida por un futuro orquestador, IT3+)
**Fecha**: 2026-08-03

---

## Módulo

`src/banking/connectors/ing.py`

---

## Clase pública: `IngConnector`

```python
class IngConnector:
    def __init__(self, http_client: httpx.Client | None = None) -> None: ...

    def fetch_transactions(
        self, start_date: date, end_date: date
    ) -> list[Transaction]: ...
```

**Constructor**:
- `http_client`: opcional. Si se omite, el conector construye su propio
  `httpx.Client` apuntando a la API real de Enable Banking. Los tests
  **siempre** inyectan un cliente construido con `httpx.MockTransport`
  (FR-014) — este es el único punto de extensión necesario para mockear
  todas las llamadas HTTP sin parchear internals del módulo.

**Método `fetch_transactions`**:
- **Entrada**: `start_date`, `end_date` — ambos `datetime.date`. Rango
  inclusivo evaluado sobre la fecha de liquidación (ver `data-model.md`).
- **Salida (éxito)**: `list[Transaction]` — solo transacciones `BOOK`,
  normalizadas, deduplicadas. Puede ser una lista vacía (no es un error).
- **Salida (fallo)**: no retorna; lanza una de las excepciones listadas en
  `data-model.md` → Entidad 5. Nunca retorna una lista parcial.
- **Efecto secundario**: exactamente un log estructurado por invocación
  (éxito o fallo), más un log `WARNING` por cada registro omitido por campos
  faltantes (ver `research.md` → Decisión 8).

**Precondiciones de configuración** (leídas internamente, no son parámetros):
- `~/.config/banca-personal/eb-config.json` (`app_id`, `private_key_path`)
- `SecretStore.get("ENABLE_BANKING_SESSION_ID")`

---

## Ejemplo de uso (referencia, no es código de test)

```python
from datetime import date
from banking.connectors.ing import IngConnector

connector = IngConnector()
transactions = connector.fetch_transactions(
    start_date=date(2026, 8, 1),
    end_date=date(2026, 8, 31),
)
for tx in transactions:
    print(tx.booking_date, tx.amount, tx.currency, tx.description)
```

## Ejemplo de test (referencia, no reemplaza `tasks.md`)

```python
import httpx
from banking.connectors.ing import IngConnector

def test_fetch_transactions_single_page(mock_master_key: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [...], "continuation_key": None})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = IngConnector(http_client=client)
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))
    assert len(result) == ...
```

---

## Errores expuestos (importables desde `banking.connectors.ing`)

- `ConnectorConfigError`
- `InvalidDateRangeError`
- `ReauthorizationRequiredError`
- `RateLimitExceededError`
- `PaginationLimitExceededError`
- `EnableBankingAPIError`

Ver `data-model.md` → Entidad 5 para cuándo se lanza cada una.
