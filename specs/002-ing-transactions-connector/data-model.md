# Modelo de Datos: Conector de Movimientos ING España (Enable Banking)

**Salida de Fase 1 para**: `specs/002-ing-transactions-connector/plan.md`
**Fecha**: 2026-08-03

Esta funcionalidad no introduce ninguna base de datos ni almacenamiento
persistente (FR-009). Las siguientes son estructuras de datos en memoria
(value objects) que existen únicamente durante una invocación del conector.

---

## Entidad 1: SolicitudRangoFechas (`DateRangeRequest`)

**Propósito**: Los parámetros de entrada de una invocación del conector.

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `start_date` | `datetime.date` | Debe ser anterior o igual a `end_date` |
| `end_date` | `datetime.date` | Debe ser posterior o igual a `start_date` |

**Reglas de validación**:
- Si `start_date > end_date` → `InvalidDateRangeError` antes de cualquier
  llamada a la API (FR-011).

**Semántica del rango** (decidida en `/speckit-clarify`):
- Se evalúa sobre la **fecha de liquidación** (`booking date`) de cada
  transacción devuelta por la API.
- El rango es **inclusivo** en ambos extremos: una transacción fechada
  exactamente en `start_date` o en `end_date` se incluye en el resultado.

---

## Entidad 2: CredencialDeFirma (`SigningCredential`)

**Propósito**: La identidad de aplicación y clave privada usadas para firmar
cada JWT de autenticación.

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `app_id` | `str` | Leído de `eb-config.json`, campo `app_id` |
| `private_key` | Objeto de clave privada RSA (`cryptography`) | Cargado desde el fichero en `eb-config.json`, campo `private_key_path`, vía `load_pem_private_key` |

**Origen**: `~/.config/banca-personal/eb-config.json` (establecido por IT1).

**Manejo de ausencia/error** (Caso Límite del spec):
- Fichero ausente, no legible, o JSON inválido → `ConnectorConfigError`
- Falta `app_id` o `private_key_path` → `ConnectorConfigError`
- La ruta de clave privada no existe, o el contenido no es una clave RSA
  privada válida → `ConnectorConfigError`

**Invariante de seguridad** (FR-015): Este objeto, ni su representación en
texto, aparece jamás en ningún mensaje de log o de excepción.

---

## Entidad 3: SesiónPSD2 (`PSD2Session`)

**Propósito**: La credencial de acceso a los datos de la cuenta ING España,
de larga duración (90-180 días), sin mecanismo de refresh.

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `session_id` | `str` | Leído vía `SecretStore.get("ENABLE_BANKING_SESSION_ID")` (mecanismo cifrado de IT1) |

**Estados** (relevantes para este conector, no hay tabla de estados
persistida — se infieren de la respuesta de la API en cada invocación):

```
        ┌───────────┐   HTTP 403 o campo de estado == "expired"   ┌──────────────────────────┐
        │  válida   │ ───────────────────────────────────────────▶│ inutilizable (requiere   │
        │ (asumida) │                                              │ re-autorización manual)  │
        └───────────┘                                              └──────────────────────────┘
```

No existe una transición de vuelta a "válida" dentro del conector: la única
recuperación es un flujo de consentimiento manual por navegador, fuera del
alcance de esta funcionalidad (Suposición del spec).

**Invariante de seguridad** (FR-015): El valor completo de `session_id` nunca
aparece en ningún mensaje de log o de excepción.

---

## Entidad 4: Transacción (`Transaction`)

**Propósito**: Un movimiento de cuenta liquidado (`status: BOOK`), ya
normalizado, devuelto por el conector.

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `booking_date` | `datetime.date` | Fecha de liquidación; determina si la transacción cae en el rango solicitado |
| `amount` | `decimal.Decimal` | Positivo si `CRDT` (crédito/ingreso), negativo si `DBIT` (débito/gasto) — FR-007 |
| `currency` | `str` | Código ISO 4217 de 3 letras (p. ej. `EUR`) |
| `description` | `str` | Descripción/contraparte de la transacción, tal como la reporta la API |

**Clave de deduplicación** (no es un campo persistido, se calcula):
`(booking_date, amount, description)` — usada solo durante la recopilación de
páginas para descartar registros repetidos por solape de paginación (FR-013,
decidido en `/speckit-clarify`).

**Reglas de filtrado y validación**:
- Solo se construyen instancias `Transaction` para registros de la API con
  `status: BOOK`; `PDNG` e `INFO` se descartan antes de llegar a este modelo
  (FR-006).
- Un registro de la API sin `amount`, `currency`, `status`, o indicador
  `CRDT`/`DBIT` se omite con un log `WARNING`, sin construir una instancia
  `Transaction` y sin abortar el resto de la recuperación (FR-012).

**Estados no representados**: `PDNG` (pendiente) e `INFO` (informativa) no
tienen representación en este modelo — son filtrados antes de la
normalización, no un estado del objeto `Transaction`.

---

## Entidad 5: Errores del conector (jerarquía de excepciones)

Todas definidas en `src/banking/connectors/ing.py` (mismo patrón que
`ConfigurationError`/`DecryptionError` en `secret_store.py`, IT1 — YAGNI, sin
módulo de excepciones separado).

| Excepción | Cuándo se lanza | FR relacionado |
|-----------|------------------|-----------------|
| `ConnectorConfigError` | `eb-config.json` ausente/inválido, clave privada ausente/inválida | Caso Límite |
| `InvalidDateRangeError` | `start_date > end_date` | FR-011 |
| `ReauthorizationRequiredError` | HTTP 403, o campo de estado de sesión `expired` | FR-004 |
| `RateLimitExceededError` | HTTP 429 (petición inicial o de paginación) | FR-008 |
| `PaginationLimitExceededError` | Se alcanza `MAX_PAGES` sin agotar `continuation_key` | Caso Límite |
| `EnableBankingAPIError` | Cualquier otro error HTTP inesperado (500, 502, etc.) | Caso Límite |

**Invariante común**: Ninguna de estas excepciones acepta ni almacena en su
mensaje la clave privada, el JWT firmado, ni el `session_id` completo
(FR-015).

**Invariante de "todo o nada"**: Si cualquiera de estas excepciones se lanza
en cualquier punto de la recuperación (incluso a mitad de paginación), el
conector no devuelve ninguna lista parcial de transacciones al llamador
(Historia de Usuario 2, Escenario 3).
