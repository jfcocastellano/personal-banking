# Modelo de Datos: Escritor Genérico de Google Sheets

**Salida de Fase 1 para**: `specs/003-google-sheets-writer/plan.md`
**Fecha**: 2026-08-09

Esta funcionalidad no introduce ninguna base de datos ni almacenamiento
persistente (FR-009). Las siguientes son estructuras de datos en memoria
que existen únicamente durante una invocación del componente.

---

## Entidad 1: CredencialDeCuentaDeServicio (`ServiceAccountCredential`)

**Propósito**: El JSON de la cuenta de servicio de Google Cloud usado para
autenticar cada invocación.

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `info` | `dict[str, Any]` | Deserializado de `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")` vía `json.loads()`; debe contener como mínimo los campos que `gspread`/Google requieren (`type`, `project_id`, `private_key`, `client_email`, `token_uri`, entre otros) |

**Origen**: Secreto cifrado ya reservado por IT1 bajo la clave
`GOOGLE_SHEETS_CREDENTIALS` (`contracts/secret-store-format.md`, IT1).

**Manejo de ausencia/error** (Caso Límite del spec):
- Clave ausente en el `SecretStore` → `SheetsConfigError`
- Valor almacenado no es JSON válido → `SheetsConfigError`
- `gspread.service_account_from_dict()` rechaza el contenido (campos
  faltantes o inválidos) → `SheetsConfigError`

**Invariante de seguridad** (FR-012): Este valor, ni su representación en
texto, aparece jamás en ningún mensaje de log o de excepción.

---

## Entidad 2: SolicitudDeEscritura (`WriteRequest`)

**Propósito**: Los parámetros de entrada de una invocación (FR-002).

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `document_id` | `str` | ID del documento de Google Sheets; no se valida su forma, se usa tal cual en `open_by_key` |
| `tab_name` | `str` | Nombre exacto de la pestaña destino; comparación exacta (sensible a mayúsculas/minúsculas, según el comportamiento nativo de Sheets) |
| `headers` | `list[CellValue]` | Fila de cabeceras; puede estar vacía (caso límite no cubierto explícitamente por el spec — se escribe tal cual, incluso vacía) |
| `rows` | `list[list[CellValue]]` | Lista de filas de datos; puede estar vacía (Historia 1, Escenario 2) |

Donde `CellValue = str | int | float | bool | None` (decidido en
`/speckit-clarify` — ver spec, `Clarifications`).

**Reglas de validación**: Ninguna sobre la forma de `rows` respecto a
`headers` (FR-006) — no se valida ni corrige el número de columnas por
fila.

---

## Entidad 3: Documento (`Document`) y Pestaña (`Tab`)

**Propósito**: Recursos externos en Google Sheets, resueltos en cada
invocación — no hay estado propio del componente entre invocaciones.

| Campo | Tipo | Restricciones |
|-------|------|----------------|
| `document_id` | `str` | Debe existir y estar compartido con la cuenta de servicio con permiso de edición (Suposición del spec) |
| `tab_name` | `str` | Si no existe en el documento, se crea (FR-003); si existe, se sobrescribe por completo (FR-004) |

**Transiciones de estado de la pestaña** (por invocación, no persistidas):

```
  ┌───────────────┐   worksheet(tab_name) → WorksheetNotFound   ┌─────────────────────┐
  │  no existe    │ ────────────────────────────────────────────▶│  creada (vacía)     │
  └───────────────┘                                              └──────────┬──────────┘
                                                                             │ update(headers + rows)
  ┌───────────────┐   worksheet(tab_name) → Worksheet existente             ▼
  │  ya existe    │ ────────────────────────────────────────────▶  clear() ─────────────▶ escrita
  └───────────────┘
```

En ambos caminos, el estado final es el mismo: la pestaña contiene
exactamente la fila de cabeceras y las filas de datos de la invocación
actual, comenzando en `A1`.

---

## Entidad 4: Resultado de la escritura (interno, no expuesto como objeto)

**Propósito**: Los datos que se registran en el log de éxito (FR-007). No
es un valor de retorno de la función pública (ver `contracts/` — el método
`write()` no retorna nada útil al llamador; el efecto observable es el log
y el estado de la pestaña).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `tab_name` | `str` | Pestaña afectada |
| `rows_written` | `int` | Número de filas de datos (sin contar la cabecera) |
| `duration_seconds` | `float` | Duración de la operación completa, medida desde el inicio de la invocación hasta el final (éxito o fallo) |

---

## Entidad 5: Errores del componente (jerarquía de excepciones)

Todas definidas en `src/banking/sheets/writer.py` (mismo patrón plano que
`src/banking/connectors/ing.py`, IT2 — sin clase base compartida, YAGNI).

| Excepción | Cuándo se lanza | FR relacionado |
|-----------|------------------|-----------------|
| `SheetsConfigError` | Secreto de cuenta de servicio ausente, JSON inválido, o rechazado por `gspread` al autenticar | FR-008(a) |
| `SheetsAccessError` | Documento inexistente o sin permiso de edición para la cuenta de servicio | FR-008(b) |
| `SheetsQuotaExceededError` | HTTP 429 de la API de Google Sheets | FR-008(c) |
| `SheetsAPIError` | Cualquier otro error inesperado de la API (500, etc.) o excepción no cubierta de `gspread` | FR-008(d) |

**Invariante común**: Ninguna de estas excepciones acepta ni almacena en su
mensaje el JSON de la cuenta de servicio ni ningún token de acceso derivado
de él (FR-012).

**Invariante de "todo o nada" en el log**: Cualquiera de estas excepciones,
en cualquier punto de la operación (incluso a mitad de la escritura, tras
`clear()`), produce exactamente un log de fallo antes de propagarse al
llamador (FR-008); no hay reintento automático (Suposición del spec).
