# Contrato: API de Google Sheets consumida vía `gspread`

**Funcionalidad**: Escritor Genérico de Google Sheets (IT3)
**Tipo**: Contrato de API externa consumida (a través de la librería `gspread`)
**Fecha**: 2026-08-09

> **Importante**: A diferencia del contrato equivalente de IT2
> (`enable-banking-api.md`), este documento describe una superficie
> **verificada contra la documentación oficial de `docs.gspread.org`**
> (2026-08-09), no una suposición sin confirmar. El único punto marcado
> **[verificar]** no ha sido probado contra una llamada real todavía — se
> confirmará en la validación manual opcional de `quickstart.md`.

---

## Autenticación

```python
import gspread
client = gspread.service_account_from_dict(info)  # info: dict ya deserializado
```

- `info` es el JSON de la cuenta de servicio, deserializado con
  `json.loads()` desde `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")`.
- Scopes por defecto (`gspread.auth.DEFAULT_SCOPES`): lectura/escritura de
  Sheets y Drive. No se pasan scopes explícitos.
- Credenciales rechazadas (campos faltantes/inválidos) → excepción de
  `gspread`/`google-auth` al construir el cliente; el componente la traduce
  a `SheetsConfigError`.

---

## Abrir el documento

```python
spreadsheet = client.open_by_key(document_id)  # -> gspread.Spreadsheet
```

- Documento inexistente o sin permiso de edición para la cuenta de
  servicio → `gspread.exceptions.SpreadsheetNotFound`.
- **[verificar]**: si un fallo de permisos (403) se traduce siempre en
  `SpreadsheetNotFound`, o si en algún caso se propaga como
  `gspread.exceptions.APIError` con `response.status_code == 403`. El
  componente captura ambas para mayor seguridad.

## Localizar o crear la pestaña

```python
try:
    worksheet = spreadsheet.worksheet(tab_name)   # -> gspread.Worksheet
except gspread.exceptions.WorksheetNotFound:
    worksheet = spreadsheet.add_worksheet(
        title=tab_name, rows=1, cols=max(len(headers), 1)
    )
else:
    worksheet.clear()
```

- `worksheet(title)` lanza `WorksheetNotFound` si no existe — se captura
  como señal de "crear", no como error de cara al llamador.
- `add_worksheet(title, rows, cols)` crea la pestaña nueva.
- `clear()` borra la totalidad del contenido existente (todas las celdas,
  filas y columnas usadas), sin necesidad de conocer su tamaño previo.

## Escribir los datos

```python
worksheet.update(values=[headers, *rows])
```

- Sin pasar `range_name`, `gspread` escribe comenzando en `A1` (cumple
  FR-005).
- `values` es una lista de listas de primitivos JSON-serializables
  (`str`, `int`, `float`, `bool`, `None`) — sin transformación previa por
  parte del componente (FR-006, FR-010).

---

## Errores de la API subyacente

| Excepción de `gspread` | Condición | Traducida a |
|--------------------------|-----------|--------------|
| `SpreadsheetNotFound` | Documento inexistente o inaccesible | `SheetsAccessError` |
| `APIError` con `response.status_code == 429` | Cuota de la API excedida | `SheetsQuotaExceededError` |
| `APIError` con `response.status_code` en `{403, 404}` (al abrir documento) | Documento inaccesible (variante alternativa al caso anterior) | `SheetsAccessError` |
| `APIError` (cualquier otro código) | Error inesperado de la API (500, etc.) | `SheetsAPIError` |
| Cualquier otra excepción de `gspread`/`google-auth` durante la autenticación | Credenciales inválidas o rechazadas | `SheetsConfigError` |

`WorksheetNotFound` **no** aparece en esta tabla — no es un error, es la
señal interna para crear la pestaña (FR-003).

---

## Uso en tests (mocks)

Todos los tests inyectan un doble de prueba en lugar de un
`gspread.Client` real — nunca se realiza una petición de red real (FR-011).
El doble debe implementar como mínimo la superficie usada arriba:
`open_by_key`, y en el objeto `Spreadsheet` resultante: `worksheet`,
`add_worksheet`; y en el objeto `Worksheet`: `clear`, `update`. Los
fixtures de test deben cubrir, como mínimo: pestaña ya existente con
contenido previo, pestaña inexistente, documento inaccesible
(`SpreadsheetNotFound`), cuota excedida (`APIError` 429), y un error de API
inesperado (`APIError` 500).
