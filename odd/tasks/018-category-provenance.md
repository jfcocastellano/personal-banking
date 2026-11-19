# 018 — De dónde sale la categoría: qué campo trae valores usables

Status: in progress.

## Por qué

La tarea 017 midió `merchant_category_code` en producción y el resultado fue
negativo: el nombre del campo llega en los dos bancos, el **valor** viene vacío en
el 100 % de los registros.

| Run | Fecha | ING España | Revolut |
| --- | --- | --- | --- |
| `43238023775` | 2026-11-12 | `mcc_populated=0/29` | `0/3` |
| `43718478631` | 2026-11-15 | `0/35` | `0/7` |
| `44114043933` | 2026-11-17 | `0/39` | `0/9` |
| `44330217832` | 2026-11-18 | `0/41` | `0/9` |

Consecuencia: la columna `Categoría` de la pestaña cruda está vacía en todas las
filas, y la pestaña `Gastos` agrupa el mes completo en una única fila
`SIN CATEGORÍA`. El código de la tarea 017 (mapa ISO 18245 +
`category_cell`) es correcto y está sin uso.

El objetivo no es borrar eso todavía: es **averiguar qué campo trae de verdad una
categoría**, en qué formato y con qué vocabulario, antes de decidir si se
reemplaza, se complementa o se revierte.

## Lo que no se sabe (y no se puede saber desde el repo)

`bank_transaction_code` es la categorización propia de la entidad y llega como
objeto `{description, code, sub_code}`. Sabemos que la **clave** aparece en ambos
bancos (run del 2026-11-18). No sabemos:

- si trae valores o viene a `null`, `{}` o con cadenas vacías;
- el vocabulario real (qué `description` usa ING España y cuál Revolut);
- si `code`/`sub_code` son numéricos, alfanuméricos o nulos;
- si basta para agrupar gastos con sentido o es demasiado grueso.

Sin credenciales locales (no hay `.env` ni `~/.config/banca-personal` en esta
máquina) la única vía es un sondeo que corra dentro del workflow, donde sí están
los secretos. Igual que en 017, el sondeo viaja en el `fetch` que ya ocurre: no
gasta ninguna petición PSD2 extra.

## Frontera de PII (no negociable)

El log de Actions no es un sitio para datos personales. Lo que este sondeo puede
escribir:

| Campo | ¿Se registra? | Por qué |
| --- | --- | --- |
| `bank_transaction_code.description` | sí, vocabulario acotado | es la categoría que asigna el banco, no el comercio ni la persona |
| `bank_transaction_code.code` / `sub_code` | sí, valores distintos acotados | identificadores de categoría |
| `merchant_category_code` | sí (ya en 017) | ISO 18245, es una categoría |
| `creditor` / `debtor` | **no** | el nombre puede ser una persona |
| `remittance_information`, importes, fechas, `entry_reference` | **no** | PII o datos del movimiento |

Si en algún momento hace falta la contraparte para categorizar por reglas, será
una decisión aparte y con otra técnica (agregados, no valores).

## Alcance

### T1 — Sondear la forma y el vocabulario de `bank_transaction_code`

Una segunda línea `INFO` por fetch, junto a la del sondeo de 017, con:

- `btc_populated=N/M` — registros con al menos una cadena no vacía entre
  `description`, `code` y `sub_code`;
- `btc_keys=…` — sub-claves vistas (unión, ordenadas);
- `btc_codes=12/32;…` — pares `code/sub_code` distintos, acotados;
- `btc_labels=Kortköp|Utlandsbetalning` — `description` distintos, acotados.

Acotados a 10 valores por lista, con marca explícita de truncamiento (`+K`), para
que la línea no crezca sin límite. Un registro cuyo `bank_transaction_code` no sea
objeto no aborta nada: se cuenta como no poblado. Test-first.

### T2 — Leer la respuesta y decidir (no hay código aquí)

Con una corrida posterior a T1:

- **Si trae valores**: el vocabulario es el insumo de un mapa banco→categoría, y
  el agrupamiento de la pestaña `Gastos` se reapunta a ese campo. Ese mapeo es una
  tarea nueva con su propio spec.
- **Si viene vacío**: se acaba la vía nativa. Las opciones son reglas sobre texto
  del movimiento (con la conversación de PII que eso abre) o aceptar que la
  categoría es manual y revertir la presentación inerte de 017.

### T3 — (condicional a T2) Reapuntar la categoría

Solo si T2 encuentra datos. Fuera de alcance por ahora: implementarlo sobre una
hipótesis es exactamente el error que 017 cometió.

## Coste y cuota

El sondeo no añade peticiones. La respuesta necesita una corrida: o la del cron
del día (gratis, va a ocurrir), o un `workflow_dispatch` que se suma a la del cron
del mismo día UTC (dos pasadas, 6 GET por cuenta, escenario ya observado el
2026-11-09 sin fallo pero contra el techo declarado de 4). **Decisión del owner.**

## Criterios de aceptación

- La línea `category provenance` aparece una sola vez por fetch, con `records=N` y
  sin ningún valor de contraparte, importe, fecha ni `remittance_information`.
- Sin registros, no hay línea.
- `bank_transaction_code` ausente, `null`, no-objeto o con todas las cadenas vacías
  cuenta como no poblado y no rompe el fetch.
- Vocabulario y códigos acotados a 10 con marca de truncamiento.
- `ruff check`, `ruff format --check`, `mypy src` y la suite completa en verde.

## Evidencia

Se anota aquí al cerrar cada tarea.

### T1 — implementada (sondeo de forma y vocabulario)

RED antes de GREEN: seis de los siete tests nuevos fallaban con el sondeo antiguo,
porque la línea `category provenance` no existía.

```text
FAILED test_fetch_reports_the_bank_transaction_code_vocabulary
FAILED test_fetch_treats_an_unusable_bank_transaction_code_as_unpopulated[absent]
FAILED ... [nulls] [empty-object] [not-an-object] [list]
6 failed, 1 passed (el de «sin registros», que pasa trivialmente)
```

GREEN: `7 passed`, suite completa `388 passed`, `ruff check`/`format` y `mypy src`
limpios.

Segunda línea `INFO` por fetch, junto a la de 017:

```text
Connector ING España: category provenance, records=41, btc_populated=N/41, btc_keys=code,description,sub_code, btc_codes=..., btc_labels=...
```

Lo que fijan los tests:

- El vocabulario y los códigos se registran; la lista se corta a 10 valores y el
  corte se ve en la propia línea (`+K`), no se esconde.
- `bank_transaction_code` ausente, `null`, `{}`, una cadena o una lista cuentan como
  **no poblado** y el movimiento sigue su curso: el sondeo nunca pierde una
  transacción.
- Sin registros no hay línea; varias páginas producen una sola.
- Ningún valor de importe, fecha ni `remittance_information` aparece en la línea.

Un test existente hubo que tocarlo: `_field_probe_lines` filtraba por `"keys="`,
subcadena que la línea nueva contiene en `btc_keys=`, así que pasó a filtrar por
`"transaction fields, records="`. El filtro era una trampa para el siguiente que
añadiera un sondeo, no un test roto.

**Lo que esto no responde:** si el campo trae valores en producción. Eso es T2 y
necesita una corrida real; los tests prueban la medición, no el dato.
