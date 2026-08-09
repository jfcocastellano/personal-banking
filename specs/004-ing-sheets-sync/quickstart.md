# Guía de Validación: Pipeline de Sincronización ING → Google Sheets

Esta guía valida el pipeline completo de extremo a extremo usando dobles
de prueba (siempre, en CI) y, opcionalmente, una ejecución real contra ING
y Google Sheets (manual, solo local — Principio III).

**Prerrequisitos**: Entornos de IT1, IT2 y IT3 ya configurados
(`BANKING_MASTER_KEY`, `eb-config.json` + clave privada real, `session_id`
PSD2 real, `GOOGLE_SHEETS_CREDENTIALS` real) — ver los `quickstart.md` de
cada iteración. Para la Parte B además: `GOOGLE_SHEET_ID` configurado.

---

## Parte A — Validación con dobles de prueba (siempre disponible)

### Paso 1 — Ejecutar los tests del pipeline

```bash
pytest tests/unit/test_sync.py tests/unit/test_cli_sync.py -v
```

**Esperado**: Todos los tests pasan. Ninguno realiza una llamada de red
real (ambos externos — `IngConnector` y `SheetsWriter` — se inyectan como
dobles de prueba).

### Paso 2 — Verificar el camino feliz (referencia)

```python
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from banking.connectors.ing import IngConnector, Transaction
from banking.sheets.writer import SheetsWriter
from banking.sync import run_sync

connector = Mock(spec=IngConnector)
connector.fetch_transactions.return_value = [
    Transaction(date(2026, 8, 1), Decimal("42.50"), "EUR", "Nómina"),
    Transaction(date(2026, 8, 3), Decimal("-12.30"), "EUR", "Supermercado"),
]
writer = Mock(spec=SheetsWriter)

result = run_sync(
    connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
)

assert result.tab_name == "2026-08"
assert result.rows_written == 2
writer.write.assert_called_once_with(
    document_id="doc-id",
    tab_name="2026-08",
    headers=["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"],
    rows=[
        ["2026-08-01", "ING España", "Nómina", 42.5, "EUR"],
        ["2026-08-03", "ING España", "Supermercado", -12.3, "EUR"],
    ],
)
print("OK — transformación y escritura correctas")
```

**Esperado**: `OK — transformación y escritura correctas`.

### Paso 3 — Verificar que un fallo de ING no escribe en Sheets (referencia)

```python
from unittest.mock import Mock

from banking.connectors.ing import IngConnector, ReauthorizationRequiredError
from banking.sheets.writer import SheetsWriter
from banking.sync import IngSyncError, run_sync

connector = Mock(spec=IngConnector)
connector.fetch_transactions.side_effect = ReauthorizationRequiredError("re-autorización requerida")
writer = Mock(spec=SheetsWriter)

try:
    run_sync(connector=connector, writer=writer, document_id="doc-id")
    print("FAIL — debería haber lanzado IngSyncError")
except IngSyncError as e:
    writer.write.assert_not_called()
    print(f"OK — {e}")
```

**Esperado**: `OK — re-autorización requerida`, y `writer.write` nunca
invocado.

### Paso 4 — Verificar el comando CLI completo (referencia)

```bash
python -m banking sync --help  # confirma que el subcomando está registrado
```

**Esperado**: Ayuda del subcomando `sync`, sin error de "unknown command".

---

## Parte B — Validación manual con sistemas reales (opcional, solo local)

> Requiere sesión PSD2 real de ING (IT2), cuenta de servicio real de
> Google (IT3), y un documento de Google Sheets real compartido con esa
> cuenta de servicio. **No se ejecuta en CI.** Consume cuota real de la
> API de Enable Banking (máx. 4 peticiones/cuenta/día) — no repetir esta
> prueba más de una vez al día.

### Paso 5 — Configurar el documento destino

```bash
python -m banking secrets set GOOGLE_SHEET_ID <tu-document-id-real>
```

### Paso 6 — Ejecutar la sincronización real

```bash
python -m banking sync
```

**Esperado**: El comando completa en menos de 2 minutos (SC-006), imprime
un resumen con "ING España", el número de movimientos del mes en curso, la
pestaña `YYYY-MM` correspondiente, y la duración. La pestaña en el
documento de Google Sheets muestra las columnas `Fecha de liquidación,
Banco, Descripción, Importe, Divisa` con los movimientos reales del mes.

### Paso 7 — Verificar la idempotencia same-day

```bash
python -m banking sync
```

**Esperado**: Segunda ejecución el mismo día — la pestaña `YYYY-MM` queda
con el mismo contenido (o actualizado si hubo un movimiento nuevo entre
ambas ejecuciones), sin ninguna fila duplicada.

---

## Checklist de validación

| Paso | Descripción | Pasa cuando |
|------|-------------|-------------|
| 1 | Suite de tests del pipeline | Todos pasan, sin red real |
| 2 | Transformación y escritura (camino feliz) | Filas y cabeceras correctas, tipos numéricos preservados |
| 3 | Fallo de ING no escribe en Sheets | `IngSyncError`, `writer.write` no invocado |
| 4 | Registro del subcomando CLI | `python -m banking sync --help` funciona |
| 5-7 | Validación manual (opcional) | Ejecución real exitosa, idempotente el mismo día |

---

## Notas

- La Parte A es la que se ejecuta en CI (`ci.yml`, IT1) como parte de
  `pytest tests/`.
- La Parte B es manual, local, y consume cuota real de PSD2 — no
  automatizar ni incluir en CI (Principio III).
