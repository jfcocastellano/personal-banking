# Contrato: `python -m banking sync` (capa CLI)

`banking.cli.sync`. Extiende el contrato de IT5 (`specs/005-multi-bank-resilient-sync/contracts/cli-sync-interface.md`)
con el enganche de la notificación por email y el exit code 4. Mismo subcomando, sin argumentos
nuevos.

## Invocación

```
python -m banking sync
```

Sin argumentos nuevos respecto a IT5.

## Firma del handler (extendida)

```python
def handle(
    args: argparse.Namespace,
    notifier: EmailNotifier | None = None,
) -> int: ...
```

- `notifier`: opcional, inyección de dependencias para tests (mismo patrón que `run_sync`).
  Si se omite, se construye `EmailNotifier()` en producción. Los tests inyectan
  `Mock(spec=EmailNotifier)`.

## Flujo de terminación (FR-013)

En cada rama, la notificación ocurre **antes** de devolver el exit code, y el resumen de la
ejecución se imprime siempre que hay datos que mostrar:

1. **Fallo total** (`run_sync` lanza `AllBanksFailedError`): imprime el error en stderr (formato
   IT5), notifica con los `outcomes` de la excepción, y devuelve `1` — o `4` si la entrega falló.
2. **Fallo de Sheets** (`run_sync` lanza `SheetsSyncError`): imprime el error en stderr (formato
   IT5), notifica con los `outcomes` de la excepción + `sheets_error`, y devuelve `2` — o `4` si la
   entrega falló.
3. **Retorno normal** (`SyncSummary`): imprime el resumen en stdout (formato IT5) y devuelve `0`
   (éxito completo) o `3` (fallo parcial). Si el estado es `PARTIAL_FAILURE`, notifica antes de
   devolver — o devuelve `4` si la entrega falló (el resumen ya está impreso).
4. **Éxito completo**: el notificador NO se invoca (FR-003) — cero llamadas.

## Tabla resumen de códigos de salida

| Código | Condición |
|---|---|
| `0` | Los 4 bancos sincronizados y escritos (sin email, FR-003) |
| `1` | Los 4 bancos fallaron (`AllBanksFailedError`) — nada escrito; email enviado o omitido |
| `2` | ≥1 banco exitoso, pero falló la escritura en Sheets (`SheetsSyncError`); email enviado o omitido |
| `3` | ≥1 banco exitoso y ≥1 banco fallido, escritura exitosa; email enviado o omitido |
| `4` | **Fallo de entrega de la notificación** (`DeliveryStatus.FAILED`) — el resumen de la ejecución ya se imprimió; el desenlace de sincronización sigue identificable (FR-006) |

Precedencia: si el desenlace de sincronización es un fallo (1/2/3) y además la entrega del email
falla, el código devuelto es `4` (la entrega es el último fallo observado y el más accionable desde
el scheduler de IT7). Si la entrega se omite por configuración ausente (`SKIPPED`, FR-007) o tiene
éxito (`SENT`), manda el código del desenlace.

## Contexto pasado al notificador

| Rama | `outcomes` | `sheets_error` | `tab_name` | `duration_seconds` |
|---|---|---|---|---|
| Fallo total | `exc.outcomes` (los 4, fallidos) | `None` | `exc.tab_name` | `0.0` |
| Fallo de Sheets | `exc.outcomes` (los obtenidos) | `str(exc)` | `exc.tab_name` | `0.0` |
| Fallo parcial | `summary.outcomes` | `None` | `summary.tab_name` | `summary.duration_seconds` |

Si `exc.outcomes` es `None` (invocador antiguo sin contexto), el notificador aplica su fallback
defensivo (ver `contracts/notify-interface.md`).

## Salida en fallo de entrega (exit 4)

Además del resumen/error del desenlace ya impreso, una línea en stderr:

```
ERROR (notificación): no se pudo enviar el email de aviso — <motivo>
```

Sin secretos en el motivo (FR-008).

## Restricciones

- Ningún mensaje impreso incluye credenciales, JWT, `session_id` completo, ni JSON de cuenta de
  servicio (FR-014 de IT5, FR-008 de IT6).
- `cli/sync.py` es el único módulo de esta funcionalidad que puede llamar a `print()`
  (Anti-patrón #6); `notify.py` y `sync.py` (núcleo) solo usan `logging`.
- `handle()` mantiene complejidad ciclomática ≤ 10 mediante los helpers `_finish_total_failure` y
  `_finish_sheets_failure` (Principio VI).

## Verificación de contrato (tests)

`tests/unit/test_cli_sync.py` invoca `handle()` con `run_sync` y `EmailNotifier` mockeados:
- Los 4 casos de IT5 (exit 0/1/2/3) siguen pasando con `notify_failure` → `SENT` o `SKIPPED`.
- Exit 4 cuando `notify_failure` → `FAILED`, en cada rama fallida, con el resumen impreso.
- El notificador se invoca exactamente una vez en cada rama fallida y **cero veces** en éxito
  completo (FR-003).
- El caso combinado banco+escritura pasa `outcomes` con fallos + `sheets_error` no nulo (FR-002).
