# Contrato: `run_sync()` — núcleo de orquestación multi-banco

`banking.sync.run_sync`. Reemplaza la versión de un solo banco de IT4 (mismo nombre de función,
firma y tipo de retorno distintos — ver `research.md` Decisión 4).

## Firma

```python
def run_sync(
    connectors: Sequence[EnableBankingConnector] | None = None,  # 4 instancias, orden ING/Revolut/MyInvestor/Sabadell
    writer: SheetsWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> SyncSummary: ...
```

`connectors=None` (valor por defecto en producción) construye internamente las 4 instancias reales
(`IngConnector()`, `RevolutConnector()`, `MyInvestorConnector()`, `SabadellConnector()`) en ese
orden fijo. Los tests inyectan una secuencia de 4 dobles (`Mock(spec=<Connector>)`).

## Comportamiento

1. Calcula `range_start` (día 1 del mes en curso) y `tab_name` (`YYYY-MM`) igual que IT4.
2. Para cada conector, en orden:
   - Llama a `connector.fetch_transactions(range_start, execution_date)`.
   - Éxito → `BankOutcome(bank_name=connector.BANK_NAME, succeeded=True, rows_written=len(txs), failure_reason=None)`.
   - Excepción → se captura, se registra (`logger.error`, sin credenciales), y se produce
     `BankOutcome(bank_name=connector.BANK_NAME, succeeded=False, rows_written=None, failure_reason=str(exc))`.
   - Ningún fallo interrumpe el bucle (FR-002).
3. Si los 4 `BankOutcome.succeeded` son `False` → lanza `AllBanksFailedError` (nueva excepción; el
   mensaje agrega los 4 motivos). No se llama a `SheetsWriter`.
4. Si al menos 1 es `True` → combina las filas transformadas de los bancos exitosos (mismo orden),
   llama una sola vez a `writer.write(...)` con el conjunto combinado.
   - Éxito de escritura → devuelve `SyncSummary` con `overall_status` `FULL_SUCCESS` o
     `PARTIAL_FAILURE` según corresponda.
   - Fallo de escritura → lanza `SheetsSyncError` (ya existente desde IT4, sin cambio de semántica).

## Excepciones

| Excepción | Cuándo | Contiene |
|---|---|---|
| `AllBanksFailedError` | Los 4 conectores fallaron | Los 4 motivos, sin credenciales |
| `SheetsSyncError` | ≥1 banco exitoso, pero la escritura combinada falló | El motivo del `SheetsWriter`, sin credenciales |

Ninguna otra excepción debe escapar de `run_sync()` sin controlar (FR-008 / Anti-patrón #9).

## Postcondiciones

- Retorno normal (`SyncSummary`) ⟺ al menos 1 banco tuvo éxito Y la escritura en Sheets tuvo éxito.
- `AllBanksFailedError` ⟺ los 4 bancos fallaron; la pestaña de Sheets no se toca en absoluto.
- `SheetsSyncError` ⟺ al menos 1 banco tuvo éxito pero la escritura falló; el estado final de la
  pestaña es el que ya documenta `SheetsWriter` ante un fallo a mitad de operación (sin garantía
  transaccional adicional, igual que IT4).

## Verificación de contrato (tests, FR-013)

- **Todos ok**: los 4 dobles devuelven movimientos → `SyncSummary.overall_status == FULL_SUCCESS`,
  `total_rows_written` correcto, `writer.write` llamado una vez con las filas combinadas.
- **Un banco falla, los otros tres continúan**: 1 doble lanza una excepción, los otros 3 devuelven
  movimientos → `SyncSummary.overall_status == PARTIAL_FAILURE`, `outcomes` refleja el banco fallido
  con su motivo, `writer.write` llamado una vez solo con las filas de los 3 exitosos.
- **Todos fallan**: los 4 dobles lanzan → `run_sync()` lanza `AllBanksFailedError`, `writer.write`
  NO se llama.
