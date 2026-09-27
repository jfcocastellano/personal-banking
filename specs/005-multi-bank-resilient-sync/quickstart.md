# Quickstart: Validación de la sincronización multi-banco

## Prerrequisitos

- Entorno ya configurado desde IT1-IT4: `BANKING_MASTER_KEY` en el entorno del SO, `.env` cifrado
  con `GOOGLE_SHEET_ID` y `GOOGLE_SHEETS_CREDENTIALS`.
- `eb-config.json` de Enable Banking ya presente (compartido entre los 4 bancos, sin cambios de
  formato respecto a IT2).
- **Paso de migración manual** (una sola vez, ver `research.md` Decisión 3): renombrar la entrada
  existente `ENABLE_BANKING_SESSION_ID` en el `.env` cifrado a `ENABLE_BANKING_SESSION_ID_ING`:

  ```
  python -m banking secrets get ENABLE_BANKING_SESSION_ID
  python -m banking secrets set ENABLE_BANKING_SESSION_ID_ING <valor obtenido>
  python -m banking secrets delete ENABLE_BANKING_SESSION_ID   # si el subcomando existe; si no, editar .env directamente
  ```

- Añadir las 3 claves de sesión nuevas, cada una ya autorizada vía el flujo de consentimiento del
  banco correspondiente en Enable Banking (fuera del alcance de esta funcionalidad — ver spec.md §
  Suposiciones):

  ```
  python -m banking secrets set ENABLE_BANKING_SESSION_ID_REVOLUT <session_id de Revolut>
  python -m banking secrets set ENABLE_BANKING_SESSION_ID_MYINVESTOR <session_id de MyInvestor>
  python -m banking secrets set ENABLE_BANKING_SESSION_ID_SABADELL <session_id de Sabadell>
  ```

## Validación automatizada (CI, sin red real)

```
pytest tests/unit -q
ruff check .
ruff format --check .
mypy src
```

Confirma en particular:
- `tests/unit/connectors/test_enable_banking.py` — lógica PSD2 compartida.
- `tests/unit/connectors/test_{ing,revolut,myinvestor,sabadell}.py` — `BANK_NAME` y clave de sesión
  por banco.
- `tests/unit/test_sync.py` — los 3 escenarios obligatorios (FR-013): todos ok, un banco falla,
  todos fallan.
- `tests/unit/test_cli_sync.py` — los 4 códigos de salida (ver `contracts/cli-sync-interface.md`).

## Validación manual end-to-end (opcional, contra APIs reales)

1. Ejecutar:

   ```
   python -m banking sync
   ```

2. **Camino feliz**: si los 4 bancos tienen sesión válida, confirmar en Google Sheets que la
   pestaña `YYYY-MM` del mes en curso contiene movimientos de los 4 bancos, y que la salida de
   consola muestra `Sincronización completada: 4/4 bancos` con código de salida `0`
   (`echo $?` / `$LASTEXITCODE`).

3. **Fallo parcial**: revocar o dejar expirar deliberadamente la sesión de un solo banco (p. ej.
   Revolut) y volver a ejecutar. Confirmar: los otros 3 bancos siguen apareciendo en la pestaña, la
   consola muestra `Sincronización parcial: 3/4 bancos` con el motivo del fallo de Revolut, y el
   código de salida es `3`.

4. **Fallo total**: no viable de forma realista contra las 4 APIs reales simultáneamente sin
   revocar las 4 sesiones; se considera suficientemente cubierto por el escenario obligatorio
   mockeado en `test_sync.py` (FR-013c). Si se desea validar manualmente, revocar las 4 sesiones y
   confirmar que no se escribe nada en Sheets, que la consola muestra
   `ERROR: los 4 bancos fallaron` en stderr, y que el código de salida es `1`.

## Presupuesto de rendimiento (SC-006)

Medir la duración impresa en el resumen (`<T>s`) tras el camino feliz (paso 2): debe ser inferior a
120s. No hay techo de tiempo por banco a nivel de orquestador (ver spec.md § Clarifications) — si
esta medición se excede de forma reproducible por un banco concreto, es una señal para revisar ese
conector individualmente, no el pipeline.
