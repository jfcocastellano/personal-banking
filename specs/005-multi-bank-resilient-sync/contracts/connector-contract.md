# Contrato: Conector de banco Enable Banking

Aplica a los cuatro conectores en scope: `IngConnector`, `RevolutConnector`, `MyInvestorConnector`,
`SabadellConnector` (`banking.connectors.<banco>`). Formaliza FR-011 de la spec.

## Interfaz pública

```python
class <Banco>Connector:
    BANK_NAME: str  # atributo de clase, p. ej. "ING España", "Revolut", "MyInvestor", "Banco Sabadell"

    def __init__(
        self, http_client: httpx.Client | None = None, config_dir: Path | None = None
    ) -> None: ...

    def fetch_transactions(self, start_date: date, end_date: date) -> list[Transaction]:
        """Devuelve los movimientos liquidados (BOOK) en [start_date, end_date], ambos inclusive."""
```

## Precondiciones

- `start_date <= end_date`, si no → `InvalidDateRangeError`.
- Existe `eb-config.json` (compartido entre los 4 bancos) con `app_id` y `private_key_path`
  válidos, si no → `ConnectorConfigError`.
- Existe una clave de sesión PSD2 propia de ese banco en el `SecretStore`
  (`ENABLE_BANKING_SESSION_ID_<BANCO>`), si no → se propaga el error del `SecretStore`
  (`KeyError`/`DecryptionError`/`ConfigurationError`).

## Postcondiciones (éxito)

- Devuelve una lista de `Transaction` (posiblemente vacía) sin duplicados, deduplicados por
  `(booking_date, amount, description)`.
- No efectúa ningún efecto secundario visible más allá de las llamadas HTTP salientes a Enable
  Banking.

## Categorías de error (comunes a los 4 bancos)

| Excepción | Disparador |
|---|---|
| `ConnectorConfigError` | `eb-config.json`, `app_id`, `private_key_path`, o la clave privada, ausentes o inválidos |
| `InvalidDateRangeError` | `start_date > end_date` |
| `ReauthorizationRequiredError` | HTTP 403 al consultar la sesión, o estado `"expired"` reportado por la API |
| `RateLimitExceededError` | HTTP 429 (límite de 4 peticiones/cuenta/día) |
| `EnableBankingAPIError` | Cualquier otro HTTP inesperado, o sesión sin cuentas vinculadas |
| `PaginationLimitExceededError` | La API sigue devolviendo `continuation_key` tras el límite máximo de páginas |

Ninguna de estas excepciones, ni su mensaje, incluye el JWT, la clave privada, ni el `session_id`
completo (FR-004).

## Diferencias explícitas entre bancos

Ninguna a nivel de código: los 4 conectores comparten toda la lógica (JWT, resolución de sesión,
paginación, parseo, mapeo de errores HTTP) vía `EnableBankingConnector`
(`banking.connectors.enable_banking`, ver `research.md` Decisión 1). Cada uno fija únicamente:

- `BANK_NAME` (constante de clase, usada en la columna "Banco" y en el resumen)
- La clave de sesión PSD2 en el `SecretStore` (constante de clase interna, `_SESSION_ID_KEY`)

## Verificación de contrato (tests)

- La lógica compartida se verifica una sola vez en `tests/unit/connectors/test_enable_banking.py`.
- Cada `tests/unit/connectors/test_<banco>.py` verifica únicamente que `BANK_NAME` y la clave de
  sesión son los esperados para ese banco (la clase hereda el resto sin sobrescribirlo).
