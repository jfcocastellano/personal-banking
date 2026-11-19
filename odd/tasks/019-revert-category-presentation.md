# 019 — Revertir la columna y la suma agrupada por categoría

Status: closed (2026-11-19). Revert applied, 374 tests, `ruff` y `mypy` limpios.

## Por qué

La tarea 017 añadió una columna `Categoría` a la pestaña cruda y convirtió la
pestaña `Gastos` en un sumatorio por categoría. La tarea 018 fue a medir si el
banco mandaba algo que poner ahí, y la respuesta fue que no:

| Campo | ING España | Revolut |
| --- | --- | --- |
| `merchant_category_code` | `0/44` — la clave llega, el valor no | `0/9` — ídem |
| `bank_transaction_code` | `44/44` poblado, pero `description="Banca online"` para **todos**, sin `code`/`sub_code` | `9/9` poblado, sin `description`; `code` ∈ {`ATM`, `CARD_PAYMENT`, `TOPUP`} |

Ninguno de los dos dice qué se compró: traen canal de operación, no categoría de
comercio. Con ese dato, la presentación de 017 no muestra una categoría: muestra
una columna vacía y una pestaña `Gastos` con una única fila `SIN CATEGORÍA` que
suma el mes. Es una funcionalidad que declara algo falso —que hubo agrupación—
sobre un campo que nunca va a llegar.

Decisión del owner (2026-11-19): **revertir**, y dejar la categorización manual de
`G:H` como única fuente de categoría. El motor de reglas sobre el texto del
movimiento queda como idea sin spec, no como trabajo pendiente encubierto.

## Alcance

Reversión mecánica de `82cedbd` (el merge de 017/T4), conservando lo que sí sirve:

- **Fuera** el campo `merchant_category_code` de `Transaction` y de
  `_parse_transaction`: nadie lo consumía ya.
- **Fuera** `src/banking/categories.py` y `tests/unit/test_categories.py`: mapa
  ISO 18245 correcto sobre datos que no existen.
- **Fuera** la columna `Categoría` de la pestaña `<YYYY-MM>` (vuelve a
  `B3:E…` con fecha, banco, descripción, importe).
- **Fuera** el bloque de sumatorios por categoría de `Gastos`: la pestaña vuelve a
  listar los movimientos individuales en `B4:E403`, y «Gastos»/«Ingresos» vuelven
  a ser dos `SUMIF` sobre la columna de importes.
- **La cabecera entra en la región que se reescribe** (`B3:E403` en vez de
  `B4:E403`), para que una pestaña creada durante 017/T4 se corrija en la
  siguiente corrida en vez de quedarse con `CATEGORÍA`/`TOTAL` encima de una lista
  de movimientos. De paso, la cabecera del bloque pasa a ser una única tupla
  (`_EXPENSE_HEADERS`) que usan la creación y el refresco, así que no pueden
  divergir.
- **Se queda** el panel de saldos `J:K` y el catálogo manual `G:H`, que son
  independientes de esto.
- **Se queda** el sondeo de `_FieldProbe`/`_BankTransactionCodeProbe`. Es lo único
  que documenta por qué la hoja no tiene categoría, y su coste es una línea de log
  por fetch, sin peticiones PSD2 extra.

## Cómo se hizo

`git revert --no-commit 82cedbd` sobre una rama nueva. Un solo conflicto real, en
`quickstart.md`, porque después del merge de T4 se documentó la medición de 018 en
ese mismo bloque: se conservó la descripción del layout revertido y se sustituyó
la frase «falta medir» por el número medido.

Dos cosas que el revert automático no resolvió bien:

1. Borró `_optional_text`, que nació en T4/S2, pero el sondeo que añadió 018 lo
   usaba para normalizar el MCC. Se reapuntó a `_non_empty_text`, que ya existía y
   hace exactamente lo mismo (cadena recortada no vacía o nada), en vez de
   reintroducir un helper con un solo consumidor.
2. Borró la sección T4 del documento de 017, que es historia y no código. Se
   restauró el fichero y se le puso una marca de «revertido en 019».

`odd/tasks/017-sheet-order-and-transaction-fields.md` conserva así el registro
completo: lo que se construyó, por qué se construyó y por qué no sobrevivió.

## Verificación

- `pytest`: **374 passed** (eran 388; se van los tests del mapa de categorías y de
  la columna, y entra el de la cabecera).
- `ruff check`, `ruff format --check` (54 ficheros) y `mypy src` (25 módulos, uno
  menos: `categories.py`) sin hallazgos.
- Ninguna referencia a `banking.categories` ni a la columna en `src/`.

## Efecto secundario bueno

Desaparece el riesgo de `rows_written` que 017/T4 dejó abierto: el resumen decía
«N filas en la pestaña `<YYYY-MM> Gastos`» con N = movimientos, mientras la
pestaña tenía **una** fila. Con la lista de movimientos de vuelta, el número
vuelve a coincidir con lo que hay en la hoja.

## Verificación de la cabecera

Un test nuevo (`test_second_run_repairs_a_header_left_by_the_category_layout`)
planta `CATEGORÍA`/`TOTAL` en la fila 3 de una pestaña existente y comprueba que la
siguiente escritura la deja en `FECHA`/`BANCO`/`DESCRIPCIÓN`/`IMPORTE`. El doble de
`Worksheet` de los tests acepta ahora `B3:E403` (401 filas: cabecera + 400
movimientos) en vez de `B4:E403`, y sigue rechazando cualquier escritura fuera de
esa región y de `J:K`.

## Riesgos

- **Una pestaña de un mes pasado no se repara hasta que se reescribe.** La
  cabecera se corrige en la siguiente pasada que toque ese mes; para `2026-11` es
  automático porque está en curso, y para un mes anterior hace falta un
  `banking layout --month` explícito. Coste bajo: una corrida manual.
- Si algún día se retoma la categoría automática, la tabla de reglas sobre texto
  del movimiento tiene una conversación de PII pendiente: el nombre de una
  transferencia a una persona vive en `remittance_information`.
