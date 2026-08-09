# Contrato: Interfaz Pública del Escritor de Google Sheets

**Funcionalidad**: Escritor Genérico de Google Sheets (IT3)
**Tipo**: Interfaz Python interna (consumida por un futuro pipeline, IT4+)
**Fecha**: 2026-08-09

---

## Módulo

`src/banking/sheets/writer.py`

---

## Tipo: `CellValue`

```python
CellValue = str | int | float | bool | None
```

Alias de tipo para los valores individuales aceptados en `headers` y en
cada fila de `rows` (decidido en `/speckit-clarify`; ver spec).

---

## Clase pública: `SheetsWriter`

```python
class SheetsWriter:
    def __init__(self, client: gspread.Client | None = None) -> None: ...

    def write(
        self,
        document_id: str,
        tab_name: str,
        headers: list[CellValue],
        rows: list[list[CellValue]],
    ) -> None: ...
```

**Constructor**:
- `client`: opcional. Si se omite, el componente construye su propio
  `gspread.Client` autenticado con la cuenta de servicio leída de
  `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")`. Los tests **siempre**
  inyectan un doble de prueba (FR-011) — este es el único punto de
  extensión necesario para mockear toda interacción con Google Sheets sin
  parchear internals del módulo.

**Método `write`**:
- **Entrada**:
  - `document_id`: ID del documento de Google Sheets (`str`).
  - `tab_name`: nombre exacto de la pestaña destino (`str`).
  - `headers`: fila de cabeceras (`list[CellValue]`).
  - `rows`: filas de datos (`list[list[CellValue]]`), puede ser `[]`.
- **Salida (éxito)**: `None`. El efecto observable es el estado final de la
  pestaña (creada o sobrescrita, ver `data-model.md` → Entidad 3) y un log
  `INFO` (ver abajo).
- **Salida (fallo)**: no retorna; lanza una de las excepciones listadas en
  `data-model.md` → Entidad 5.
- **Efecto secundario**: exactamente un log estructurado por invocación:
  - Éxito: `INFO` con `tab_name`, `rows_written` (número de filas de datos,
    sin contar la cabecera), `duration_seconds`.
  - Fallo: `ERROR` con `tab_name`, la categoría del fallo (nombre de la
    excepción) y un motivo breve, sin datos sensibles (FR-012).

**Precondición de configuración** (leída internamente si `client` no se
inyecta, no es un parámetro):
- `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")`

---

## Ejemplo de uso (referencia, no es código de test)

```python
from banking.sheets.writer import SheetsWriter

writer = SheetsWriter()
writer.write(
    document_id="1AbCdEfGhIjKlMnOpQrStUvWxYz",
    tab_name="2026-08",
    headers=["fecha", "importe", "divisa", "descripción"],
    rows=[
        ["2026-08-01", 42.50, "EUR", "Nómina"],
        ["2026-08-03", -12.30, "EUR", "Supermercado"],
    ],
)
```

## Ejemplo de test (referencia, no reemplaza `tasks.md`)

```python
from unittest.mock import Mock
import gspread
from banking.sheets.writer import SheetsWriter

def test_write_overwrites_existing_tab() -> None:
    worksheet = Mock(spec=gspread.Worksheet)
    spreadsheet = Mock(spec=gspread.Spreadsheet)
    spreadsheet.worksheet.return_value = worksheet
    client = Mock(spec=gspread.Client)
    client.open_by_key.return_value = spreadsheet

    writer = SheetsWriter(client=client)
    writer.write("doc-id", "2026-08", ["a", "b"], [[1, 2]])

    worksheet.clear.assert_called_once()
    worksheet.update.assert_called_once_with(values=[["a", "b"], [1, 2]])
```

---

## Errores expuestos (importables desde `banking.sheets.writer`)

- `SheetsConfigError`
- `SheetsAccessError`
- `SheetsQuotaExceededError`
- `SheetsAPIError`

Ver `data-model.md` → Entidad 5 para cuándo se lanza cada una.
