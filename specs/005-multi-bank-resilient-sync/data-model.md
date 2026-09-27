# Fase 1: Modelo de Datos — Sincronización Multi-Banco con Resiliencia Parcial

Todas las entidades son estructuras de datos puras en memoria (dataclasses `frozen=True`, sin
persistencia, sin comportamiento más allá de construcción y lectura), consistente con el Principio
VII (sin base de datos ni capa de persistencia).

## `Transaction` (sin cambios, ya existente desde IT2)

Definida en `banking.connectors.enable_banking` (movida desde `banking.connectors.ing`, misma
forma). Un movimiento liquidado (`BOOK`) normalizado de un banco.

| Campo | Tipo | Notas |
|---|---|---|
| `booking_date` | `date` | Fecha de liquidación |
| `amount` | `Decimal` | Positivo (crédito) o negativo (débito) |
| `currency` | `str` | Código ISO 4217 |
| `description` | `str` | `remittance_information` concatenado |

## `BankOutcome` (nuevo)

El desenlace de ejecutar el conector de un banco concreto en una ejecución.

| Campo | Tipo | Notas |
|---|---|---|
| `bank_name` | `str` | `<Connector>.BANK_NAME` |
| `succeeded` | `bool` | `True` si el conector devolvió movimientos sin lanzar |
| `rows_written` | `int \| None` | Nº de movimientos, solo si `succeeded` |
| `failure_reason` | `str \| None` | Mensaje del error capturado, solo si no `succeeded` — nunca incluye credenciales/JWT/session_id completo (FR-004) |

Invariante: exactamente uno de (`rows_written`, `failure_reason`) es `None`, determinado por
`succeeded`.

## `OverallStatus` (nuevo, `enum.Enum`)

| Valor | Significado |
|---|---|
| `FULL_SUCCESS` | Los 4 `BankOutcome` tienen `succeeded=True` |
| `PARTIAL_FAILURE` | Al menos 1 `succeeded=True` y al menos 1 `succeeded=False`; Sheets escrito con los datos disponibles |
| `TOTAL_FAILURE` | Los 4 `BankOutcome` tienen `succeeded=False`; Sheets NO escrito |

No existe un cuarto valor para "fallo del propio paso de Sheets": ese caso se señala lanzando
`SheetsSyncError` (FR de IT4, sin cambios), no como parte de `SyncSummary.overall_status` — ver
`contracts/sync-pipeline-interface.md`.

## `SyncSummary` (nuevo, reemplaza el `SyncResult` de un solo banco de IT4)

El agregado de los 4 `BankOutcome` de una misma ejecución, más el resultado global.

| Campo | Tipo | Notas |
|---|---|---|
| `outcomes` | `list[BankOutcome]` | Longitud fija 4, en el orden ING/Revolut/MyInvestor/Sabadell |
| `overall_status` | `OverallStatus` | Ver arriba |
| `tab_name` | `str` | Pestaña `YYYY-MM` destino (o la que se hubiera usado, en fallo total) |
| `total_rows_written` | `int` | Suma de `rows_written` de los bancos exitosos; `0` en fallo total |
| `duration_seconds` | `float` | Duración total de la ejecución |

## Conector bancario (contrato, no una clase concreta)

Ver `contracts/connector-contract.md` para la interfaz formal. A nivel de modelo de datos, cada
conector expone:

| Miembro | Tipo | Notas |
|---|---|---|
| `BANK_NAME` | `str` (atributo de clase) | Nombre para columnas y resumen |
| `fetch_transactions(start_date, end_date)` | `(date, date) -> list[Transaction]` | Igual firma que IT2 |

Implementaciones en esta iteración: `IngConnector`, `RevolutConnector`, `MyInvestorConnector`,
`SabadellConnector` — las 4 heredan de `EnableBankingConnector` (ver `research.md`, Decisión 1),
que no es en sí misma una entidad del dominio sino un detalle de implementación compartido.

## Fila de Google Sheets (sin cambios de esquema respecto a IT4)

Cada `Transaction` exitoso se transforma a una fila con el mismo orden fijo de columnas ya
establecido: fecha de liquidación, nombre del banco (`BankOutcome.bank_name` / `Connector.BANK_NAME`),
descripción, importe, divisa. Los movimientos de los 4 bancos exitosos se concatenan en una sola
lista de filas antes de una única llamada a `SheetsWriter.write()` (FR-005).
