# Guía de Validación: Escritor Genérico de Google Sheets

Esta guía valida que el componente funciona de extremo a extremo usando
dobles de prueba (por defecto, y suficiente para CI) y, opcionalmente,
un documento de Google Sheets real ya compartido con una cuenta de
servicio (manual, solo local — Principio III).

**Prerrequisitos**: Entorno de IT1 ya configurado (`BANKING_MASTER_KEY`
exportado, dependencias instaladas).

---

## Parte A — Validación con dobles de prueba (siempre disponible, sin credenciales reales)

### Paso 1 — Instalar las nuevas dependencias

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

**Esperado**: `gspread` instalado en la versión pineada (y sus
dependencias transitivas, incluida `google-auth`).

### Paso 2 — Ejecutar los tests del componente

```bash
pytest tests/unit/sheets/test_writer.py -v
```

**Esperado**: Todos los tests pasan. Ninguno realiza una llamada de red
real (verificable: los tests pueden correr con la red desconectada).

### Paso 3 — Verificar la sobrescritura de una pestaña existente (referencia)

```python
from unittest.mock import Mock
import gspread
from banking.sheets.writer import SheetsWriter

worksheet = Mock(spec=gspread.Worksheet)
spreadsheet = Mock(spec=gspread.Spreadsheet)
spreadsheet.worksheet.return_value = worksheet  # la pestaña ya existe
client = Mock(spec=gspread.Client)
client.open_by_key.return_value = spreadsheet

writer = SheetsWriter(client=client)
writer.write(
    document_id="doc-id",
    tab_name="2026-08",
    headers=["fecha", "importe"],
    rows=[["2026-08-01", 42.50]],
)

assert worksheet.clear.called
assert worksheet.update.called
print("OK — borrado y reescritura desde A1")
```

**Esperado**: `OK — borrado y reescritura desde A1`.

### Paso 4 — Verificar la creación automática de pestaña (referencia)

```python
from unittest.mock import Mock
import gspread
from banking.sheets.writer import SheetsWriter

new_worksheet = Mock(spec=gspread.Worksheet)
spreadsheet = Mock(spec=gspread.Spreadsheet)
spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound
spreadsheet.add_worksheet.return_value = new_worksheet
client = Mock(spec=gspread.Client)
client.open_by_key.return_value = spreadsheet

writer = SheetsWriter(client=client)
writer.write("doc-id", "2026-09", ["a"], [])

assert spreadsheet.add_worksheet.called
assert new_worksheet.clear.called is False  # pestaña nueva, nada que borrar
assert new_worksheet.update.called
print("OK — pestaña creada y escrita")
```

**Esperado**: `OK — pestaña creada y escrita`.

### Paso 5 — Verificar el error de documento inaccesible (referencia)

```python
from unittest.mock import Mock
import gspread
from banking.sheets.writer import SheetsWriter, SheetsAccessError

client = Mock(spec=gspread.Client)
client.open_by_key.side_effect = gspread.exceptions.SpreadsheetNotFound

writer = SheetsWriter(client=client)
try:
    writer.write("doc-inexistente", "2026-08", ["a"], [])
    print("FAIL — debería haber lanzado SheetsAccessError")
except SheetsAccessError as e:
    print(f"OK — {e}")
```

**Esperado**: Un mensaje claro que identifica el documento como
inaccesible. El mensaje no debe contener el JSON de la cuenta de servicio.

---

## Parte B — Validación manual con un documento real (opcional, solo local)

> Esta parte requiere una cuenta de servicio de Google Cloud real, con la
> API de Sheets habilitada, y un documento de Google Sheets ya compartido
> con el email de esa cuenta de servicio (permiso de editor). **No se
> ejecuta en CI.**

### Paso 6 — Configurar el JSON de la cuenta de servicio

```bash
python -m banking secrets set GOOGLE_SHEETS_CREDENTIALS "$(cat ruta/a/tu-cuenta-de-servicio.json)"
```

### Paso 7 — Ejecutar una escritura real sobre una pestaña de prueba

```python
from banking.sheets.writer import SheetsWriter

writer = SheetsWriter()  # sin client → cliente real
writer.write(
    document_id="<tu-document-id-real>",
    tab_name="prueba-quickstart",
    headers=["columna_a", "columna_b"],
    rows=[["valor1", 1], ["valor2", 2]],
)
print("Escritura real completada — revisa la pestaña 'prueba-quickstart' en el documento")
```

**Esperado**: La invocación completa sin error en menos de 30 segundos
(SC-006), y la pestaña `prueba-quickstart` del documento indicado muestra
exactamente las dos filas de datos bajo la cabecera, comenzando en `A1`.
Si el documento no existe o no está compartido con la cuenta de servicio,
se espera `SheetsAccessError` con un mensaje claro.

> Este paso valida el objetivo original de la funcionalidad: confirmar que
> la autenticación real y la escritura funcionan de extremo a extremo
> contra la API real de Google Sheets.

---

## Checklist de validación

| Paso | Descripción | Pasa cuando |
|------|-------------|-------------|
| 1 | Instalación de dependencias nuevas | `pip install` sale con código 0 |
| 2 | Suite de tests del componente | Todos los tests pasan, sin red real |
| 3 | Sobrescritura de pestaña existente | `clear()` y `update()` invocados |
| 4 | Creación automática de pestaña | `add_worksheet()` invocado, sin `clear()` |
| 5 | Documento inaccesible | `SheetsAccessError` con mensaje claro, sin secretos |
| 6-7 | Validación manual (opcional) | Escritura real exitosa y visible en el documento |

---

## Notas

- La Parte A es la que se ejecuta en CI (`ci.yml`, IT1) como parte de
  `pytest tests/`.
- La Parte B es manual, local, y usa credenciales reales de Google Cloud —
  no automatizar ni incluir en CI (Principio III).
