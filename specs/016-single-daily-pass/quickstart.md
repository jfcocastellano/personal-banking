# Quickstart — Pasada diaria única (crudo + layout)

**Funcionalidad**: `016-single-daily-pass` | **Fecha**: 2026-11-04

Guía de uso y de operación de la pasada diaria: un solo comando que consulta cada banco una vez y
escribe las dos pestañas del mes en curso. El día a día es un comando; el resto de esta guía explica
qué se refresca, qué queda en tus manos, y los límites que no se pueden sortear.

---

## 0. Requisitos previos

- IT4 y IT5 desplegados: los cuatro conectores y `GOOGLE_SHEET_ID` configurados.
- Las cuatro sesiones PSD2 vigentes. Un banco sin sesión no rompe la pasada: se reporta como
  `SIN SESIÓN PSD2`, sus movimientos no se escriben y la corrida no falla.
- El mismo permiso de escritura que ya usa el sync y el mismo que usa el layout (la cuenta de
  servicio comparte el documento).
- La pestaña de layout no hace falta que exista: si no está, la pasada la crea completa y después la
  actualiza.

---

## 1. Correr la pasada en local

Con `BANKING_MASTER_KEY` exportada y los secretos ya provisionados:

```bash
.venv/bin/python -m banking daily
```

El comando **no toma argumentos**. El mes es siempre el de la fecha de ejecución: si corrés esto el
3 de noviembre, escribe `2026-11` y `2026-11 Gastos`. Si el parser recibe cualquier flag, falla sin
escribir nada.

Para un mes que no es el actual, el camino es el de siempre, el backfill manual:

```bash
.venv/bin/python -m banking layout --month 2026-09
```

**Sin clave en la máquina**, que es el caso normal: el mismo `python -m banking daily` corre en
GitHub Actions, donde ya están los secretos. `Actions → Sincronización → Run workflow`. El resumen
de la ejecución trae bancos procesados, movimientos por pestaña, bancos sin sesión, fallos y
duración; no hay ninguna lógica de negocio en el workflow.

---

## 2. Qué se escribe

Dos pestañas por mes, en una sola corrida y desde la misma lectura:

| Pestaña | Qué recibe |
| --- | --- |
| `2026-11` | un movimiento por fila, ordenado por fecha y banco (`Fecha de liquidación, Banco, Descripción, Importe, Divisa`) |
| `2026-11 Gastos` | el mismo conjunto de movimientos como gastos individuales, más el resumen y el panel de saldos |

Cada banco hace **dos llamadas de datos**: una para movimientos del día 1 a hoy, una para el
saldo. El conector, además, resuelve la sesión con `GET /sessions/{session_id}` antes de cada
etapa, así que en HTTP son **4 GET por cuenta** más paginación. El margen frente al límite PSD2 de
4 peticiones por cuenta y día **no está verificado**, porque no está claro si Enable Banking cuenta
la consulta de sesión contra ese límite. Encadenar `banking sync` y `banking layout` habría sido 6
GET por cuenta y habría leído los movimientos dos veces; por eso la pasada diaria es un proceso
único.

---

## 3. Cómo leer el informe por banco

La cabecera dice cuántos bancos respondieron, cuántos movimientos fueron a la pestaña cruda y
cuántas filas a la de layout (el mismo número: es el mismo conjunto), más la duración:

```
Pasada diaria completada: 3/4 bancos — 42 movimientos en la pestaña 2026-11 y 42 filas en la pestaña 2026-11 Gastos (12.34s)
```

Debajo va una línea por banco, en orden fijo (ING España, Revolut, MyInvestor, Banco Sabadell).
Movimientos y saldo se informan por separado, porque fallan por separado:

```
  - ING España: 25 movimientos, saldo 1234.56 EUR (referencia 2026-11-04)
  - Revolut: 11 movimientos, saldo 210.00 EUR (referencia 2026-11-04)
  - MyInvestor: 6 movimientos, saldo 8450.12 EUR (sin dato de referencia)
  - Banco Sabadell: SIN SESIÓN PSD2
  Bancos sin sesión PSD2 (no cuentan como fallo): Banco Sabadell
```

Qué significan los tres casos raros:

| Línea | Qué pasó |
| --- | --- |
| `SIN SESIÓN PSD2` | el banco no tiene `session_id` provisionado. No es un fallo: no hay email, no cambia el código de salida y su fila de saldo queda sin dato |
| `saldo 1234.56 EUR (referencia 2026-11-04)` | saldo del momento de la consulta y la fecha de referencia que informa el banco, no la fecha de la corrida |
| `sin dato de referencia` | el banco devolvió saldo pero no la fecha a la que corresponde |
| `sin saldo informado` | el banco respondió sin saldo, sin lanzar error |
| `FALLÓ la consulta de saldo — <motivo>` | el saldo falló; los movimientos de ese banco se escriben igual |
| `FALLÓ la lectura de movimientos — <motivo>` | los movimientos fallaron; el saldo y el resto de los bancos siguen |

Un fallo de saldo no cambia el código de salida: se ve en la línea del banco.

---

## 4. Qué se refresca y qué no

En la pestaña `2026-11 Gastos` la propiedad está repartida, y la pasada diaria respeta ese reparto:

| Bloque | Dueño | Qué pasa en cada corrida |
| --- | --- | --- |
| `B4:E403` (gastos individuales) | la máquina | se limpia y se reescribe entero |
| `J:K` (resumen `Ingresos`/`Gastos`/`Total` y panel `SALDO CUENTAS`) | la máquina | se limpia y se reescribe entero, incluido lo que hayas tipeado ahí |
| `G:H` (categoría y total tipeado a mano) | vos | **no se toca**: sobrevive a todas las corridas |

Si editás un importe a mano dentro de `B4:E403`, la próxima pasada lo pisa. Lo mismo dentro de `J:K`:
el resumen y el panel de saldos son de la máquina y se regeneran. `G:H` es el único bloque manual, y
por eso es el único que aguanta. Los totales del resumen son fórmulas (`=SUMIF(...)`), así que un
importe corregido en `E` se refleja solo sin que nadie lo recalcule.

---

## 5. Límites que conviene conocer antes de usarlo

- **El saldo es una foto, no un histórico.** PSD2 informa el saldo del momento en que se consulta,
  con la fecha de referencia del banco al lado. Si la pasada corre el día 12, el panel muestra el
  saldo del día 12 y no el cierre del mes. No hay serie de saldos: no existe una fila por día, ni la
  habrá hasta que se implemente el snapshot diario (fecha × cuenta), que queda **fuera de alcance**
  de esta funcionalidad y es una limitación declarada, no un olvido.
- **El mes anterior deja de actualizarse.** El día 1 la pasada arranca el mes nuevo y no vuelve a
  mirar atrás: la pestaña del mes que terminó queda con lo que tenía en su última corrida. Cerrar ese
  hueco también depende del snapshot diario y tampoco está en esta funcionalidad.
- **El techo de 400 filas sigue siendo ruidoso.** Si el mes lo supera, el writer falla en vez de
  truncar en silencio.
- **La pasada no crea meses viejos.** No tiene `--month` a propósito: para eso está
  `banking layout --month`.

---

## 6. Códigos de salida

Los mismos que `banking sync`, con el mismo significado:

| Código | Significado |
| --- | --- |
| `0` | pasada completa (sin email), o todos los bancos sin sesión PSD2: no se escribió nada y no se borró nada |
| `1` | fallo total: ningún banco pudo aportar movimientos y al menos uno falló de verdad — nada escrito |
| `2` | falló la escritura en Sheets; el mensaje nombra la etapa (`raw` o `layout`) |
| `3` | fallo parcial con al menos un banco escrito; las dos pestañas se escribieron con lo disponible |
| `4` | la pasada terminó y el email de aviso no se pudo entregar (el resumen ya se imprimió) |

**Qué dice el email**: uno solo, agregado, con los bancos fallidos y su motivo, los que sí se
sincronizaron y el nombre de la pestaña. Solo se envía en `1`, `2` y `3`. En `0` no hay email, ni en
el éxito completo ni cuando todos los bancos están sin sesión.

**Cuándo una corrida escribe legítimamente nada**: cuando todos los bancos están sin sesión PSD2. En
ese caso no se lee siquiera `GOOGLE_SHEET_ID` —los writers vacían una pestaña antes de llenarla, así
que escribir ahí borraría un mes que ningún banco aportó— y el comando lo dice:

```
Pasada diaria omitida: ningún banco tiene sesión PSD2 — no se ha escrito nada en las pestañas 2026-11 y 2026-11 Gastos (0.10s)
```

No es un error: el código de salida es `0` y no hay correo.

---

## 7. Verificación manual

1. `.venv/bin/python -m banking daily` con al menos un banco con sesión.
2. Abrir la pestaña `2026-11`: los movimientos del mes hasta hoy, sin duplicados de la corrida
   anterior.
3. Abrir `2026-11 Gastos`: el mismo conjunto en `B4:E403`, y en `J:K` el resumen y el panel
   `SALDO CUENTAS` con la fecha de referencia.
4. Anotar el saldo de una cuenta, escribir un importe a mano en una celda de `H`, y volver a correr
   el comando.
5. Confirmar que el importe de `H` sigue ahí y que su `H53` sigue sumando.
6. Confirmar que `J:K` cambió si el saldo cambió, y que el importe de `H` no se movió.

Si el paso 5 falla, es un defecto del writer y no del formato: `G:H` no debe recibir escrituras en la
ruta de actualización. Si el paso 6 no cambia nada, revisá que el banco haya informado saldo nuevo
(la línea del banco lo dice).

Guía completa del layout, su geometría y sus límites: `../008-monthly-sheet-layout/quickstart.md`.
Tabla de comandos y códigos de salida del proyecto: `../../docs/context.md`.
