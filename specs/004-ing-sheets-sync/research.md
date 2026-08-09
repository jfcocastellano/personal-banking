# Investigación: Pipeline de Sincronización ING → Google Sheets

**Salida de Fase 0 para**: `specs/004-ing-sheets-sync/plan.md`
**Fecha**: 2026-08-09

Esta funcionalidad no introduce ningún sistema externo nuevo: solo conecta
dos componentes ya existentes y probados (`IngConnector`, IT2;
`SheetsWriter`, IT3). Las decisiones de abajo son de integración, no de
protocolo externo — no hay puntos `[verificar contra API real]` como en
IT2/IT3.

---

## Decisión 1: Separación núcleo/CLI

**Decisión**: La lógica de orquestación vive en un módulo núcleo,
`src/banking/sync.py` (`run_sync()`), sin ninguna llamada a `print()` ni a
`argparse`. La adaptación a línea de comandos vive en
`src/banking/cli/sync.py` (`add_parser()`, `handle()`), que llama a
`run_sync()`, captura sus excepciones, imprime el resultado y traduce a un
código de salida.

**Racional**: Mismo patrón que `cli/secrets.py` (IT1) sobre `SecretStore`:
la lógica de negocio se puede testear directamente, sin pasar por
`argparse` ni capturar stdout. Cumple el Anti-patrón #6 de la constitución
("`print()` solo en módulos de punto de entrada CLI") — `sync.py` no es un
punto de entrada, `cli/sync.py` sí.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| Toda la lógica dentro de `cli/sync.py` | Mezclaría orquestación con parsing de argumentos y `print()`; forzaría a los tests a pasar por `argparse.Namespace` para probar la lógica central |

---

## Decisión 2: Inyección de dependencias para tests

**Decisión**: `run_sync(connector: IngConnector | None = None, writer:
SheetsWriter | None = None, document_id: str | None = None, today: date
| None = None) -> SyncResult`. Si se omiten: `connector` →
`IngConnector()` real; `writer` → `SheetsWriter()` real; `document_id` →
`SecretStore().get("GOOGLE_SHEET_ID")`; `today` → `date.today()`.

**Racional**: Mismo patrón de inyección ya usado por `IngConnector`
(`http_client`) y `SheetsWriter` (`client`) en IT2/IT3. Los tests inyectan
dobles de prueba (`Mock(spec=IngConnector)`, `Mock(spec=SheetsWriter)`), un
`document_id` de prueba y una fecha fija, sin mockear internamente
`httpx`/`gspread`/`SecretStore` de nuevo — esas piezas ya están cubiertas
por los tests de IT1/IT2/IT3; este pipeline solo verifica que las llama
correctamente y transforma/orquesta bien (FR-010, FR-011). Inyectar
`document_id` directamente (en vez de forzar a cada test a preparar un
`SecretStore` con `GOOGLE_SHEET_ID` cifrado) mantiene los tests del núcleo
del pipeline enfocados en la orquestación, no en el mecanismo de secretos
ya probado en IT1.

---

## Decisión 3: Nombre del banco expuesto públicamente por `IngConnector`

**Decisión**: Añadir `IngConnector.BANK_NAME: str = _BANK_NAME` como
atributo de clase pública en `src/banking/connectors/ing.py`, reutilizando
la constante de módulo privada ya existente (`_BANK_NAME = "ING España"`,
usada internamente en 3 mensajes de log desde IT2). El pipeline usa
`IngConnector.BANK_NAME` para la columna del esquema (FR-003) y el resumen
(FR-006), en vez de un literal propio.

**Racional**: Decidido explícitamente en `/speckit-clarify` (FR-011). Es la
extensión mínima posible a un módulo ya fusionado: un atributo de clase que
reexpone una constante ya existente, sin tocar ninguna de las 3 llamadas de
log internas que ya la usan.

---

## Decisión 4: Esquema de columnas y transformación

**Decisión**: `_HEADERS = ["Fecha de liquidación", "Banco", "Descripción",
"Importe", "Divisa"]`. Por cada `Transaction` del conector:

```python
[
    tx.booking_date.isoformat(),   # str "YYYY-MM-DD"
    IngConnector.BANK_NAME,         # str
    tx.description,                 # str
    float(tx.amount),               # float — Decimal no es un CellValue válido (IT3)
    tx.currency,                    # str
]
```

**Racional**: `SheetsWriter.write()` (IT3) solo acepta primitivos
JSON-serializables (`str`, `int`, `float`, `bool`, `None`) como valor de
celda — un `Decimal` no es aceptado directamente (decidido en
`/speckit-clarify` de IT3: la conversión es responsabilidad de quien
integra los datos bancarios, es decir, esta funcionalidad). Se convierte a
`float` (no a `str`) para que la celda siga siendo numérica en Sheets y
admita fórmulas de suma — Google Sheets almacena internamente todos los
números como `double`, así que no hay pérdida de precisión adicional frente
a escribirlo como texto.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| `str(tx.amount)` para el importe | La celda quedaría como texto; rompería fórmulas de suma en la hoja, contradiciendo el propósito de un "cuadro de control" (`docs/context.md`) |

---

## Decisión 5: Rango de fechas y nombre de pestaña

**Decisión**: `range_start = execution_date.replace(day=1)`;
`range_end = execution_date`; `tab_name = execution_date.strftime("%Y-%m")`.

**Racional**: FR-002/FR-004. `date.replace(day=1)` (stdlib) obtiene el
primer día del mes sin lógica de calendario adicional. `IngConnector.
fetch_transactions()` ya trata el rango como inclusivo en ambos extremos
(IT2), por lo que no se necesita ningún ajuste adicional aquí.

---

## Decisión 6: Categorización de fallos y códigos de salida

**Decisión**: Dos excepciones nuevas en `sync.py`, planas (sin jerarquía
compartida, mismo patrón que `ing.py`/`writer.py`):

- `IngSyncError` — envuelve cualquier excepción lanzada por
  `IngConnector.fetch_transactions()` (`ConnectorConfigError`,
  `InvalidDateRangeError`, `ReauthorizationRequiredError`,
  `RateLimitExceededError`, `PaginationLimitExceededError`,
  `EnableBankingAPIError`).
- `SheetsSyncError` — envuelve cualquier excepción lanzada al leer
  `GOOGLE_SHEET_ID` del `SecretStore`, o por `SheetsWriter.write()`
  (`SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`,
  `SheetsAPIError`).

`cli/sync.py` mapea: `IngSyncError` → código `1`; `SheetsSyncError` →
código `2` (decidido en `/speckit-clarify`, FR-007/FR-008).

**Racional**: El pipeline no necesita distinguir entre las 6+4 excepciones
internas de IT2/IT3 una por una — solo necesita saber "¿qué sistema
falló?" para el código de salida y el mensaje (FR-007/FR-008); el mensaje
original de la excepción envuelta (ya sin secretos, por FR-015 de IT2 y
FR-012 de IT3) se reutiliza tal cual como motivo.

**Mecánica de aplicación**: `run_sync()` captura `Exception` de forma
amplia alrededor de cada llamada externa (a `IngConnector` y, por separado,
a `SecretStore().get("GOOGLE_SHEET_ID")` + `SheetsWriter`), no por tipo
específico — cualquier fallo de una de las dos fases se traduce a la
excepción de esa fase.

---

## Decisión 7: Logging a nivel de pipeline

**Decisión**: `run_sync()` emite, además de lo que `IngConnector`/
`SheetsWriter` ya registran internamente (IT2/IT3), un log propio:
`INFO` con banco, pestaña, filas escritas y duración en éxito; `ERROR` con
banco, sistema responsable (`"ing"` / `"sheets"`) y motivo en fallo.
`cli/sync.py` además imprime (`print()`) un resumen equivalente en éxito, o
un mensaje de error en `stderr`, ya que es el punto de entrada CLI
(Anti-patrón #6 — `print()` solo permitido ahí).

**Racional**: FR-006; deja al pipeline con su propia señal de
observabilidad completa (banco, pestaña, conteo, duración, estado), útil
para una futura integración con notificaciones por email (IT6) o el
resumen de GitHub Actions (IT7), sin depender de reconstruirlo a partir de
los logs internos de `IngConnector`/`SheetsWriter`.

---

## Decisión 8: Secreto del documento destino

**Decisión**: Cuando no se inyecta `document_id` (uso real, no en tests),
`run_sync()` lo obtiene mediante `SecretStore().get("GOOGLE_SHEET_ID")`,
dentro del mismo bloque `try` que envuelve la llamada a
`SheetsWriter.write()` (Decisión 6) — un fallo al leerlo se traduce
igualmente en `SheetsSyncError`.

**Racional**: `GOOGLE_SHEET_ID` ya está reservado como clave de secreto
desde IT1 (`contracts/secret-store-format.md`); el pipeline es exactamente
la primera funcionalidad que la consume de verdad (Suposición del spec).
Ver Decisión 2 para el motivo de exponerlo también como parámetro
inyectable de `run_sync()`.
