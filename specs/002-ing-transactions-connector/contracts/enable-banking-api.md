# Contrato: API de Enable Banking (tal como la consume este conector)

**Funcionalidad**: Conector de Movimientos ING España (Enable Banking) (IT2)
**Tipo**: Contrato de API externa consumida (no expuesta por este proyecto)
**Fecha**: 2026-08-03

> **Importante**: Este documento describe la forma asumida de la API de
> Enable Banking, a partir de `docs/context.md` y de las convenciones
> públicas conocidas de agregadores PSD2/Berlin Group. Los puntos marcados
> **[verificar]** deben confirmarse contra la documentación oficial de
> Enable Banking antes de la primera ejecución real (no mockeada). Este
> documento es la base para construir fixtures de test realistas (FR-014) y
> para aislar el código dependiente del protocolo real en `ing.py`.
>
> **Actualización 2026-08-09**: la sección de Autenticación ha sido
> verificada contra una llamada real a `GET /aspsps` (y contra
> `docs.enablebanking.com/api/quick-start/`) y corregida — la suposición
> original (PS256, `iss`/`aud` = `app_id`/URL base) era incorrecta y
> producía `401 Unauthorized`.
>
> **Actualización 2026-08-10**: primera ejecución real de extremo a
> extremo (IT4, `python -m banking sync`) contra una sesión PSD2 real de
> ING España. Reveló dos discrepancias con lo asumido más abajo, ya
> corregidas en `ing.py`:
> - El `session_id` **no** se usa directamente en la URL de transacciones.
>   Hay que resolver primero el `account_id` vía `GET /sessions/{session_id}`
>   (devuelve `{"status", "accounts": [account_id, ...]}`); el conector usa
>   el primer `account_id` de esa lista.
> - El endpoint de transacciones real es `GET /accounts/{account_id}/transactions`
>   (no `GET /sessions/{session_id}/transactions`, que devuelve `404`).
> - `remittance_information` es una **lista** de líneas de texto, no un
>   string plano; el conector las une con espacios.
> - `GET /aspsps` exige la cabecera `psu-ip-address` para el ASPSP `ING`/`ES`
>   (visible en `required_psu_headers`), relevante para `POST /auth` (fuera
>   del alcance de este conector — ver nota más abajo).

---

## Autenticación

**Verificado 2026-08-09** contra `GET /aspsps` real (200 OK tras la corrección):

- Cada petición a la API incluye un JWT firmado con **RS256** (no PS256) en
  la cabecera `Authorization: Bearer <jwt>`.
- La cabecera (header) del JWT lleva `kid` = `app_id` de `eb-config.json`
  (identificador de la aplicación registrada en Enable Banking).
- Los claims del payload son:
  - `iss`: literal fijo `"enablebanking.com"` (no el `app_id`).
  - `aud`: literal fijo `"api.enablebanking.com"` (sin esquema `https://`,
    distinto de la URL base usada para las peticiones).
  - `iat` / `exp`: timestamps Unix; TTL corto (el conector usa 300 s;
    la documentación oficial admite hasta 3600 s).
- El JWT se genera por el conector en cada petición (o al inicio de la
  invocación), usando la clave privada RSA y el `app_id` de
  `eb-config.json`. No hay intercambio previo por un access token separado
  (confirmado: la llamada a `/aspsps` con el JWT directamente devuelve 200).
- El `session_id` PSD2 identifica la autorización de consentimiento del
  usuario. **Verificado 2026-08-10**: no se usa directamente en la URL de
  transacciones — primero hay que resolver el `account_id` vía
  `GET /sessions/{session_id}`.

---

## Resolución de cuenta (verificado 2026-08-10)

```
GET /sessions/{session_id}
Authorization: Bearer <jwt>
```

Respuesta (200):

```json
{
  "status": "AUTHORIZED",
  "accounts": ["<account_id>"],
  "accounts_data": ["..."],
  "aspsp": {"name": "ING", "country": "ES"},
  "access": {"transactions": true, "balances": true, "valid_until": "..."}
}
```

El conector usa el primer elemento de `accounts`. Igual que las llamadas de
transacciones, esta respuesta pasa por la misma comprobación de sesión
utilizable (`403` → `ReauthorizationRequiredError`, `429` →
`RateLimitExceededError`, cuerpo `200` con `status: expired` →
`ReauthorizationRequiredError`).

---

## Endpoint de transacciones (verificado 2026-08-10)

```
GET /accounts/{account_id}/transactions
    ?date_from={start_date}
    &date_to={end_date}
    &continuation_key={continuation_key opcional}
Authorization: Bearer <jwt>
```

### Respuesta (200, verificada contra una cuenta ING España real)

```json
{
  "transactions": [
    {
      "status": "BOOK",
      "booking_date": "2026-08-15",
      "transaction_amount": {
        "amount": "42.50",
        "currency": "EUR"
      },
      "credit_debit_indicator": "CRDT",
      "remittance_information": ["Descripción de la transacción"]
    }
  ],
  "continuation_key": "opaque-string-or-null"
}
```

`remittance_information` es una **lista** de líneas (verificado contra la
API real); el conector las une con espacios en `Transaction.description`.

**Campos usados por el conector**:

| Campo API | Uso en el conector |
|-----------|---------------------|
| `status` | Filtrado — solo `BOOK` se conserva (FR-006); `PDNG`, `INFO` se descartan |
| `booking_date` | `Transaction.booking_date`; determina inclusión en el rango solicitado |
| `transaction_amount.amount` | Magnitud de `Transaction.amount`, con signo aplicado según `credit_debit_indicator` |
| `transaction_amount.currency` | `Transaction.currency` (ISO 4217) |
| `credit_debit_indicator` | `CRDT` → importe positivo; `DBIT` → importe negativo (FR-007) |
| `remittance_information` | `Transaction.description`; parte de la clave de deduplicación |
| `continuation_key` (nivel raíz) | Si no es `null`/ausente, dispara la siguiente petición de paginación (FR-005) |

**Campo faltante en un registro individual**: si a un elemento de
`transactions` le falta `status`, `transaction_amount`, `credit_debit_indicator`
o `booking_date`, el registro se omite con un log `WARNING` (FR-012); el
resto de la página se sigue procesando con normalidad.

---

## Códigos de error relevantes

| Código HTTP | Condición | Excepción lanzada |
|-------------|-----------|---------------------|
| `403` | Sesión rechazada por la API | `ReauthorizationRequiredError` (FR-004) |
| `200` con campo de estado `expired` **[verificar: nombre exacto del campo]** | Sesión expirada mencionada dentro de un cuerpo de respuesta 200 | `ReauthorizationRequiredError` (FR-004) |
| `429` | Límite de 4 peticiones/cuenta/día excedido | `RateLimitExceededError` (FR-008) |
| Cualquier otro código de error (`500`, `502`, etc.) | Error inesperado de la API | `EnableBankingAPIError` (Caso Límite) |

---

## Paginación

- Mientras la respuesta incluya un `continuation_key` no nulo, el conector
  repite la petición con ese valor como parámetro.
- Límite de seguridad: `MAX_PAGES = 100` peticiones de paginación por
  invocación (ver `research.md` → Decisión 5). Si se alcanza sin que la API
  deje de devolver `continuation_key`, se lanza `PaginationLimitExceededError`.

---

## Uso en tests (mocks)

Todos los tests construyen un `httpx.Client(transport=httpx.MockTransport(handler))`
donde `handler` devuelve instancias de `httpx.Response` con los cuerpos JSON
descritos arriba — nunca se realiza una petición de red real (FR-014). Los
fixtures de test deben cubrir, como mínimo: una página única, múltiples
páginas vía `continuation_key`, una página con estados mixtos
(`BOOK`/`PDNG`/`INFO`), un registro con campo faltante, HTTP 403, un cuerpo
200 con estado `expired`, HTTP 429 en la primera petición, HTTP 429 en una
petición de paginación posterior, y un HTTP 500 inesperado.
