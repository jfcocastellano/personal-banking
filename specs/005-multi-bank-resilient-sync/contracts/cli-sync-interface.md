# Contrato: `python -m banking sync` (capa CLI)

`banking.cli.sync`. Mismo subcomando ya registrado en IT4 (`banking.__main__`); el comportamiento
interno se extiende a los 4 bancos sin cambios en cómo se invoca.

## Invocación

```
python -m banking sync
```

Sin argumentos nuevos respecto a IT4.

## Salida en éxito completo (`OverallStatus.FULL_SUCCESS`)

```
Sincronización completada: 4/4 bancos — <N> movimientos escritos en la pestaña <YYYY-MM> (<T>s)
  - ING España: <n> movimientos
  - Revolut: <n> movimientos
  - MyInvestor: <n> movimientos
  - Banco Sabadell: <n> movimientos
```

Código de salida: `0`.

## Salida en fallo parcial (`OverallStatus.PARTIAL_FAILURE`)

```
Sincronización parcial: 3/4 bancos — <N> movimientos escritos en la pestaña <YYYY-MM> (<T>s)
  - ING España: <n> movimientos
  - Revolut: FALLÓ — <motivo>
  - MyInvestor: <n> movimientos
  - Banco Sabadell: <n> movimientos
```

Código de salida: `3`. Impreso en stdout (no es un fallo total del proceso; hay datos escritos).

## Salida en fallo total (`AllBanksFailedError`)

```
ERROR: los 4 bancos fallaron — no se ha escrito nada en Google Sheets
  - ING España: <motivo>
  - Revolut: <motivo>
  - MyInvestor: <motivo>
  - Banco Sabadell: <motivo>
```

Impreso en stderr. Código de salida: `1`.

## Salida en fallo de Sheets (`SheetsSyncError`)

```
ERROR (Sheets): <motivo>
```

Impreso en stderr, igual formato que IT4. Código de salida: `2`.

## Tabla resumen de códigos de salida

| Código | Condición |
|---|---|
| `0` | Los 4 bancos sincronizados y escritos |
| `1` | Los 4 bancos fallaron (`AllBanksFailedError`) — nada escrito |
| `2` | ≥1 banco exitoso, pero falló la escritura en Sheets (`SheetsSyncError`) |
| `3` | ≥1 banco exitoso y ≥1 banco fallido, escritura en Sheets exitosa con los datos disponibles |

## Restricciones

- Ningún mensaje impreso incluye credenciales, JWT, `session_id` completo, ni JSON de cuenta de
  servicio, para ninguno de los 4 bancos (FR-014).
- `cli/sync.py` es el único módulo de esta funcionalidad que puede llamar a `print()`
  (Anti-patrón #6); `sync.py` (núcleo) solo usa `logging`.

## Verificación de contrato (tests)

`tests/unit/test_cli_sync.py` invoca `handle()` con `run_sync` mockeado para producir cada uno de
los 4 casos de la tabla anterior, y verifica el código de salida devuelto y el contenido mínimo
esperado del mensaje (nombre de banco fallido + motivo, o recuento de movimientos).
