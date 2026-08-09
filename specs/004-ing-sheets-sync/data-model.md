# Modelo de Datos: Pipeline de Sincronización ING → Google Sheets

**Salida de Fase 1 para**: `specs/004-ing-sheets-sync/plan.md`
**Fecha**: 2026-08-09

Esta funcionalidad no introduce ninguna base de datos ni almacenamiento
persistente. Las siguientes son estructuras en memoria que existen
únicamente durante una invocación del pipeline.

---

## Entidad 1: RangoDeSincronización (implícito, sin dataclass propio)

**Propósito**: Los límites de fecha de una invocación.

| Campo | Origen | Restricciones |
|-------|--------|----------------|
| `range_start` | `execution_date.replace(day=1)` | Primer día del mes en curso |
| `range_end` | `execution_date` (parámetro `today`, o `date.today()`) | Fecha de ejecución; determina también el nombre de la pestaña |

No se valida explícitamente (`range_start <= range_end` siempre se cumple
por construcción, salvo que `execution_date` tenga un día anterior al 1,
lo cual no ocurre en el calendario Gregoriano).

---

## Entidad 2: FilaTransformada

**Propósito**: La representación tabular de un `Transaction` (IT2),
lista para `SheetsWriter.write()` (IT3).

| Columna | Tipo de celda | Origen |
|---------|----------------|--------|
| `Fecha de liquidación` | `str` (ISO 8601, `YYYY-MM-DD`) | `Transaction.booking_date.isoformat()` |
| `Banco` | `str` | `IngConnector.BANK_NAME` (constante pública, ver Decisión 3 de `research.md`) |
| `Descripción` | `str` | `Transaction.description` |
| `Importe` | `float` | `float(Transaction.amount)` — conversión desde `Decimal` (Decisión 4) |
| `Divisa` | `str` | `Transaction.currency` |

**Orden fijo** (FR-003): exactamente el orden de la tabla anterior — no se
reordena por ningún criterio.

**Regla de conteo**: El número de `FilaTransformada` generadas es siempre
igual a `len(transactions)`; no hay agregación ni deduplicación adicional
en este pipeline (la deduplicación por solape de página ya ocurrió dentro
de `IngConnector.fetch_transactions()`, IT2).

---

## Entidad 3: ResultadoDeSincronización (`SyncResult`)

**Propósito**: El resultado de una ejecución exitosa, devuelto por
`run_sync()` a su llamador (la capa CLI) para construir el resumen (FR-006).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `bank_name` | `str` | `IngConnector.BANK_NAME` |
| `rows_written` | `int` | Número de `FilaTransformada` escritas (puede ser 0, FR-009) |
| `tab_name` | `str` | Nombre de la pestaña destino, formato `YYYY-MM` |
| `duration_seconds` | `float` | Duración total de la ejecución (obtención + transformación + escritura) |

---

## Entidad 4: Errores del pipeline (jerarquía de excepciones)

Definidas en `src/banking/sync.py` (mismo patrón plano que `ing.py`/
`writer.py` — sin clase base compartida, YAGNI).

| Excepción | Cuándo se lanza | Código de salida (CLI) | FR relacionado |
|-----------|------------------|--------------------------|-----------------|
| `IngSyncError` | Cualquier excepción de `IngConnector.fetch_transactions()` (config, re-autorización, cuota, API, paginación, rango inválido) | `1` | FR-007 |
| `SheetsSyncError` | Fallo al leer `GOOGLE_SHEET_ID` del `SecretStore`, o cualquier excepción de `SheetsWriter.write()` (config, acceso, cuota, API) | `2` | FR-008 |

**Invariante de "no escritura si falla ING"** (FR-007): `IngSyncError` se
lanza y se propaga **antes** de que `run_sync()` invoque a `SheetsWriter`
en absoluto — no hay ninguna llamada a `write()` en ese camino.

**Invariante de seguridad**: Ninguna de las dos excepciones añade al
mensaje ningún dato más allá del `str()` de la excepción original que
envuelven; como esas excepciones originales (IT2/IT3) ya garantizan no
incluir credenciales (FR-015 de IT2, FR-012 de IT3), la propiedad se
conserva por composición, sin lógica de redacción adicional en este
pipeline.
