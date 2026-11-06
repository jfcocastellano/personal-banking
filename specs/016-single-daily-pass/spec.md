# Feature Specification: Pasada diaria única (crudo + layout)

**Feature Branch**: `016-single-daily-pass`

**Created**: 2026-11-04

**Status**: Draft (pendiente de aprobación)

**Input**: "La pestaña `2026-11 Gastos` no se va actualizando con los movimientos diarios; la de `2026-11` sí."

## Problema

Hoy existen dos comandos y dos workflows:

- `banking sync` corre todos los días por cron y escribe la pestaña cruda `YYYY-MM`.
- `banking layout` corre **solo** por `workflow_dispatch` y escribe la pestaña `YYYY-MM Gastos`.

Tres consecuencias verificadas:

1. **La pestaña de layout envejece.** Nada la actualiza a diario. Es el síntoma reportado por el usuario.
2. **El panel de saldos nunca se refresca.** `LayoutWriter`, cuando la pestaña ya existe, reescribe solo `B4:E403` (`src/banking/sheets/layout.py:435`). Las celdas `J:K` (resumen + saldos) quedaron con los valores del día en que se creó la pestaña, y `G:H` es manual a propósito.
3. **Encadenar los dos comandos duplicaría consultas.** `sync` hace 1 request por cuenta (`fetch_transactions`) y `layout` hace 2 (`fetch_transactions` + `fetch_balance`). Correr ambos son 3 requests por cuenta contra un límite PSD2 de 4 por cuenta y día, sin margen para reintentos.

## Decisión de producto (aprobada 2026-11-04)

- Comando nuevo `banking daily`: una sola pasada que consulta Enable Banking **una vez por cuenta** y escribe **las dos pestañas**. `sync` y `layout` **no cambian**: `layout` queda como herramienta de backfill manual.
- El panel de saldos (`J:K`) se refresca **siempre**, mostrando el saldo del momento de la corrida con la fecha de referencia que informa el banco.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - La hoja del mes se mantiene al día sola (Priority: P1)

El propietario abre la hoja cualquier día y las dos pestañas del mes en curso reflejan los movimientos hasta hoy, sin haber disparado nada a mano.

**Why this priority**: es el defecto reportado. Sin esto, la funcionalidad de layout existe pero no se usa.

**Independent Test**: correr `banking daily` una vez con conectores simulados y verificar que se escribieron las dos pestañas con los mismos movimientos en la misma corrida.

**Acceptance Scenarios**:

1. **Given** dos bancos que devuelven movimientos del mes, **When** se ejecuta `banking daily`, **Then** la pestaña cruda `YYYY-MM` recibe las filas de ambos bancos y la pestaña `YYYY-MM Gastos` recibe el mismo conjunto como bloque de gastos, en una sola corrida.
2. **Given** una corrida de `banking daily` ya hecha hoy, **When** el banco agrega un movimiento y se vuelve a ejecutar, **Then** ambas pestañas muestran el movimiento nuevo y no quedan filas duplicadas de la corrida anterior.
3. **Given** una corrida de `banking daily`, **When** se inspecciona el uso de la API del banco, **Then** cada cuenta fue consultada una sola vez para movimientos y una sola vez para saldo.

---

### User Story 2 - El panel de saldos deja de mentir (Priority: P2)

El propietario mira el panel `SALDO CUENTAS` de la pestaña de layout y ve el saldo de cada cuenta a la fecha de la última corrida, con la fecha de referencia del banco al lado.

**Why this priority**: hoy el panel está congelado desde la creación de la pestaña, así que muestra datos viejos con apariencia de actuales. Un número viejo sin fecha es peor que un número ausente.

**Independent Test**: crear una pestaña de layout con un saldo simulado, correr `banking daily` otra vez con saldos distintos y verificar que `J:K` cambió y que `G:H` no.

**Acceptance Scenarios**:

1. **Given** una pestaña de layout existente con saldos de ayer, **When** corre `banking daily`, **Then** las celdas del panel de saldos y del resumen se reescriben con los valores de hoy y su `reference_date`.
2. **Given** una pestaña de layout existente con importes escritos a mano en `H4:H52`, **When** corre `banking daily`, **Then** esos importes siguen intactos y `H53` sigue sumando.
3. **Given** un banco cuyo saldo falla y cuyos movimientos sí llegan, **When** corre `banking daily`, **Then** los movimientos se escriben, la fila de saldo de ese banco queda sin dato, y la corrida no falla.
4. **Given** un banco sin sesión PSD2, **When** corre `banking daily`, **Then** su fila de saldo queda sin dato, se imprime `SIN SESIÓN PSD2`, y la corrida no falla.

---

### User Story 3 - Un fallo real sigue siendo visible (Priority: P3)

El propietario recibe un correo cuando un banco falla de verdad, y no lo recibe cuando el estado es el esperado (bancos sin sesión PSD2).

**Why this priority**: el valor de la pasada diaria se pierde si un fallo real queda indistinguible del estado normal.

**Independent Test**: ejecutar la pasada con un banco que lanza un error real y verificar exit code y notificación; repetir con todos los bancos sin sesión y verificar exit 0 sin correo.

**Acceptance Scenarios**:

1. **Given** un banco que falla y otro que responde, **When** corre `banking daily`, **Then** ambas pestañas se escriben con lo disponible, la corrida termina en exit 3 y se envía un correo.
2. **Given** todos los bancos sin sesión PSD2, **When** corre `banking daily`, **Then** no se escribe ninguna pestaña (ni se borra la existente), no se envía correo y el exit code es 0.
3. **Given** todos los bancos con error real, **When** corre `banking daily`, **Then** no se escribe nada, se envía correo y el exit code es 1.

### Edge Cases

- **Cambio de mes**: en el día 1, la pasada diaria escribe el mes nuevo; la pestaña del mes anterior deja de actualizarse con lo que tenía al último día de su mes. Cerrar ese hueco (refresh final del mes anterior) queda **fuera de alcance** de esta feature y se resuelve con el snapshot diario de saldos.
- **Pestaña de layout inexistente**: se crea completa (grid, títulos fusionados, formato) y luego se aplica la actualización normal.
- **Techo de 400 filas**: se mantiene el fallo ruidoso de `build_month_grid`; nunca se trunca.
- **Falla la escritura del crudo y funciona el layout**: se considera fallo de Sheets, exit 2, con correo; no se intenta el layout.
- **Falla la escritura del layout y funcionó el crudo**: exit 2, con correo; el crudo ya escrito se conserva.
- **Un banco responde con 0 movimientos**: cuenta como éxito en ambas pestañas.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST ofrecer un comando `banking daily` que, en una sola corrida, escriba la pestaña cruda `YYYY-MM` y la pestaña de layout `YYYY-MM Gastos` del mes en curso.
- **FR-002**: `banking daily` MUST consultar los movimientos de cada cuenta una sola vez y los saldos una sola vez, reutilizando los movimientos para las dos pestañas.
- **FR-003**: Los comandos `banking sync` y `banking layout` MUST conservar su comportamiento y sus códigos de salida actuales.
- **FR-004**: La pasada diaria MUST refrescar el panel de saldos y el resumen (`J:K`) de una pestaña de layout existente, mostrando el `reference_date` informado por el banco o `sin dato de referencia`.
- **FR-005**: La pasada diaria MUST NOT escribir en `G:H` (bloque manual de gastos comunes).
- **FR-006**: La pasada diaria MUST mantener el aislamiento por banco y por etapa: un fallo de saldo no impide escribir los movimientos de ese banco, y un fallo de un banco no impide escribir los de los demás.
- **FR-007**: Un banco sin sesión PSD2 MUST tratarse como estado esperado (`SIN SESIÓN PSD2`), sin exit code de fallo y sin correo.
- **FR-008**: Si todos los bancos están sin sesión, la pasada MUST NOT escribir ninguna pestaña ni borrar contenido existente.
- **FR-009**: Los códigos de salida de `banking daily` MUST ser los mismos que los de `sync`: 0 éxito o nada que sincronizar, 1 fallo total, 2 fallo de escritura en Sheets, 3 fallo parcial con algún banco exitoso, 4 fallo de entrega del correo.
- **FR-010**: El workflow diario MUST ejecutar `banking daily` en lugar de `banking sync`, conservando los 14 secretos, el timeout, la concurrencia `banking-sync` y el step summary.
- **FR-011**: El step summary MUST informar movimientos escritos en cada pestaña, bancos sincronizados, bancos sin sesión, fallos y duración.
- **FR-012**: El correo de fallo MUST distinguir fallo parcial de total y nombrar los bancos fallidos con su motivo.

### Key Entities

- **BankRun**: resultado por banco de la pasada — movimientos, saldo, y el fallo de cada etapa por separado más la marca de "sin sesión PSD2".
- **DailySummary**: resultado agregado — runs, estado global, nombre de la pestaña cruda y de layout, filas escritas, duración.
- **Balance**: saldo en el momento de la corrida (importe, divisa, tipo, fecha de referencia del banco).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Tras una corrida diaria, ambas pestañas del mes en curso contienen exactamente los mismos movimientos, contados como filas.
- **SC-002**: Cada cuenta recibe 2 requests por corrida diaria (movimientos + saldo), medido en los tests con dobles de los conectores.
- **SC-003**: El panel de saldos de una pestaña existente cambia tras una corrida con saldos distintos, y las celdas `G4:H52` no cambian.
- **SC-004**: Con todos los bancos sin sesión, el número de escrituras a Sheets es 0.
- **SC-005**: La suite completa, `ruff check`, `ruff format --check` y `mypy src` quedan verdes con los tests nuevos.

## Assumptions

- El mes que escribe la pasada diaria es el mes de la fecha de ejecución; no hay parámetro de mes en `daily` (para backfills se usa `layout`).
- El límite PSD2 de 4 requests por cuenta y día sigue vigente; la pasada diaria usa 2 y deja margen para un reintento manual.
- `G:H` sigue siendo manual; esta feature no introduce categorización automática.
- El snapshot diario de saldos (histórico fecha × cuenta) es una feature posterior y no se implementa acá.
