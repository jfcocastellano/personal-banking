# 022 — Replicar el estilo del libro de gastos en todas las hojas

Estado: **implementada en `2026-11`** (panel de dos tablas y estilo aplicados el
2026-11-23); quedan pendientes la llamada al estilo al crear pestaña y el comando
`banking style`. Origen: `Gastos 2026 hasta 31
octubre inclusive.xlsx` (hoja `Plantilla`), extraído leyendo `xl/styles.xml` y
`xl/worksheets/sheet1.xml` del zip, sin openpyxl.

## Especificación extraída (valores reales, no interpretación)

Fuente base Arial. Alto de fila 12.75. Sin bordes (las aristas existen con
`style=None`, es decir ninguno). Sin filas alternas. Sin panel congelado. Sin color de
pestaña. Formato numérico de importes `#,##0.00 _€`.

Tres bloques verticales, cada uno con su acento:

| Zona | Fondo | Texto | Alineación |
|---|---|---|---|
| Título de bloque (fila 2, merge) | acento sólido | Arial 12 negrita, negro | centrado |
| Cabecera (fila 3) | mismo acento | Arial 12 **blanco negrita** | centrado |
| Cuerpo | sin fondo | Arial 12 negrita | importes `0.00` centrados, días a la derecha |

Acentos: gastos `FF0000` (rojo), gastos comunes `92D050` (verde), resumen `548DD4`
(azul), saldos `FABF8F` (naranja).

Anchos del original: día 10.63, concepto 29.5, cantidad 17.88, comunes 25.88/12.88,
ingresos 24.5/16.

## Decisiones del dueño

- **D1**: cuerpo en Arial 12 tal cual el original (no hay 400 filas en la práctica).
- **D2**: se mantiene el verde para gastos comunes.
- **D3**: se prueba **solo en `2026-11`**; extender al resto después de verlo.

## Mapeo a la hoja de este repo

| Región | Tratamiento |
|---|---|
| `B2:E2` título + `B3:E403` | rojo `FF0000` |
| `G:H` gastos comunes | verde `92D050` |
| «RESUMEN MES» (`J:K`) | azul `548DD4` |
| «SALDO CUENTAS» (`J:K`) | naranja `FABF8F` |
| cuerpo `B4:E403` | Arial 12 negrita, importes `0.00` centrados |

## Bloqueo (resuelto el 2026-11-22)

No había `.env` en esta máquina y `SecretStore` exige `BANKING_MASTER_KEY`. Se aclaró que
el `.env` **no existe en ningún sitio de forma permanente**: el workflow lo crea en cada
ejecución cifrando los secrets en claro (`sync.yml:98-103`, `banking secrets set`).

Resuelto así, todo en local:

- Clave en `~/.banking_master_key` (64 hex, permisos 600).
- `.env` materializado con `banking secrets set GOOGLE_SHEETS_CREDENTIALS` y
  `… GOOGLE_SHEET_ID`, que son los dos únicos valores necesarios para trabajar con la
  hoja: formatear no toca bancos ni SMTP.
- Invocación sin exponer la clave:
  `BANKING_MASTER_KEY=$(cat ~/.banking_master_key) .venv/bin/python -m banking …`

No se necesitó el scope `workflow`: la vía del `workflow_dispatch` quedó descartada.

## Implementación propuesta

`src/banking/sheets/style.py` con la especificación como datos: una función pura
`format_requests(sheet_id: int) -> list[dict]` que devuelve los `repeatCell` de
`batch_update`, sin red. Testeable sin credenciales, que es lo que permite revisar el
payload antes de tocar el documento.

Un comando `banking style --sheet 2026-11` (sin `--all` hasta que el dueño apruebe el
resultado) que abre el documento y aplica esos requests.

Detalle importante: el escritor diario limpia **valores** de `B3:E403`, no formato, así
que el estilo sobrevive a la pasada diaria. Lo que hay que cubrir es el mes nuevo: cuando
`LayoutWriter` crea una pestaña desde cero, tiene que aplicar la misma especificación, o
el mes de diciembre nace sin formato. Eso se resuelve llamando a `format_requests` desde
`layout.py` en la creación, no con un paso manual posterior.

## Criterio de aceptación

`2026-11` con los cuatro acentos, cuerpo Arial 12 negrita e importes con el formato del
original; `geometria` de la pestaña (anchos, altos) igual al original; y una segunda
ejecución del comando no cambia nada (idempotente).

## Estado del documento (verificado por API, 2026-11-22)

`Gastos Personales` tiene tres pestañas: `2026-10` (cruda), `2026-10 Gastos` (layout) y
`2026-11` (layout, sin sufijo).

**El renombrado de noviembre no se había aplicado**: el dueño lo dio por hecho, pero la
pestaña seguía llamándose `2026-11 Gastos` y no existía ninguna `2026-11`. Riesgo real:
el escritor ya apunta a `2026-11` a secas, así que la pasada siguiente habría **creado una
pestaña vacía** y los bloques manuales (`G:H`, `J:K`) habrían quedado huérfanos en la
vieja, con el dueño rellenando una pestaña que el proceso ya no toca. Renombrada por API
(`update_title`, sin tocar celdas) el 2026-11-22.

Octubre sigue con el par crudo/layout. Ninguna de las dos la escribe ya el código: funciona
como archivo y así está bien.

## Reestructuración del panel derecho (pedida el 2026-11-22)

Hoy `J4:K6` no es una tabla de ingresos: son las tres filas del resumen
(`Ingresos` / `Gastos` / `Total`). La petición es separarlas en dos tablas apiladas.

**Tabla 1 — INGRESOS**, siete filas fijas, una por concepto:

    Nómina, Acciones IB, Dividendos IB, Opciones IB, Intereses IB, MyInvestor, Parking

**Tabla 2 — RESUMEN MES**, con título, cabecera `CONCEPTO` / `CANTIDAD` y:

    Ingresos totales    = importe
    Gastos míos         = importe
    Gastos comunes      = importe
    (línea en blanco)
    Total               = importe

La aritmética del ejemplo del dueño cierra con **Total = Ingresos − Gastos míos −
Gastos comunes**: `368,39 − 1735,98 − 800,00 = −2167,59`. Eso fija el signo de los
gastos: se muestran en positivo y se restan, no se suman negativos.

Fórmulas deducibles de las que ya existen en `layout.py`:

- Ingresos totales → `_INCOME_FORMULA` (`SUMIF(...,">0",...)`)
- Gastos míos → `-SUMIF(...,"<0",...)`, el negativo de `_SPEND_FORMULA`
- Gastos comunes → `_SHARED_TOTAL_FORMULA` (`=SUM(H4:H52)`, hoy vive en `H53`)
- Total → suma y resta de las tres celdas de arriba

**Geometría**: las siete filas de ingresos ocupan hoy el sitio del resumen, así que el
bloque `RESUMEN MES` y el de `SALDO CUENTAS` bajan. Hay que rehacer las constantes
`_SUMMARY_*`, `_BALANCE_*` y `_summary_panel_last_row`, y con ellas el panel de limpieza
del escritor.

**Dos preguntas abiertas antes de tocar código**:

1. Los importes de las siete filas de ingresos, ¿se rellenan a mano o los calcula una
   fórmula? No hay transacción bancaria que distinga "Dividendos IB" de "Opciones IB".
2. `Ingresos totales`, ¿es la suma de esas siete filas, o el `SUMIF` de la columna de
   importes de gastos? Si las siete se rellenan a mano, sumarlas es lo coherente; si no,
   el `SUMIF` puede contar ingresos que no estén en ninguna de las siete.

### Respuestas del dueño

1. Las siete filas de ingresos van **a mano**.
2. `Ingresos totales` = **suma de esas siete filas** (`SUM(K4:K10)`), no el `SUMIF` de la
   columna de importes. Si una fila queda vacía, el total no la cuenta.

### Geometría implementada

| Filas | Contenido |
|-------|-----------|
| 2-3 | `INGRESOS` (título, merge `J:K`) + cabecera `CONCEPTO`/`CANTIDAD` |
| 4-10 | las siete filas de ingreso, importes a mano en `K` |
| 11 | en blanco |
| 12 | `RESUMEN MES` (título, merge `J:K`) |
| 13 | cabecera `CONCEPTO` / `CANTIDAD` |
| 14 | Ingresos totales → `=SUM(K4:K10)` |
| 15 | Gastos míos → `=-SUMPRODUCT($E$4:$E$403*($E$4:$E$403<0))` |
| 16 | Gastos comunes → `=H53` |
| 17 | en blanco |
| 18 | Total → `=K14-K15-K16` |
| 20 | `SALDO CUENTAS` (título, merge `J:K`) |
| 21 | cabecera `CUENTA` / `CANTIDAD` |
| 22-29 | hasta ocho cuentas |
| 30 | `TOTAL` de saldos |

Constantes a rehacer en `layout.py`: `_SUMMARY_FIRST_ROW`, `_SUMMARY_EXPENSE_ROW`,
`_SUMMARY_TOTAL_ROW`, `_BALANCE_TITLE_ROW`, `_BALANCE_HEADER_ROW`, `_BALANCE_FIRST_ROW`,
`_summary_panel_last_row` y `_SUMMARY_PANEL_LAST_ROW`. Con ellas se mueven el panel de
limpieza del escritor, el rango de formato de `style.py` (`_right_hand_panel`) y las
aserciones de `test_layout_grid.py` / `test_layout_writer.py`.

La fila `Saldos al` ya no existe (eliminada en `d7cf77b`), así que el Total de saldos
cierra el panel.

Efecto colateral bueno: el `#ERROR!` de la celda `Total` del resumen
(`=K4+K5`) desaparece al reescribirse esa fórmula como `=K14-K15-K16`.

## Implementación (2026-11-23)

Constantes nuevas en `layout.py`: `_INCOME_TITLE_ROW=2`, `_INCOME_HEADER_ROW=3`,
`_INCOME_FIRST_ROW=4`, `_INCOME_LAST_ROW=10`, `_SUMMARY_TITLE_ROW=12`,
`_SUMMARY_HEADER_ROW=13`, `_SUMMARY_INCOME_ROW=14`, `_SUMMARY_EXPENSE_ROW=15`,
`_SUMMARY_SHARED_ROW=16`, `_SUMMARY_TOTAL_ROW=18`, `_BALANCE_TITLE_ROW=20`,
`_BALANCE_HEADER_ROW=21`, `_BALANCE_FIRST_ROW=22`, `_SUMMARY_PANEL_LAST_ROW=30`, y la
tupla `INCOME_LABELS`.

Fórmulas finales: `K14 =SUM(K4:K10)`, `K15 =-SUMPRODUCT($E$4:$E$403*($E$4:$E$403<0))`,
`K16 =H53`, `K18 =K14-K15-K16`. La versión con `SUMIF` de tres argumentos
(`_SPEND_BODY`) se guardaba como fórmula pero se pintaba `#ERROR!` en la hoja real: está
en `es_ES` y allí Sheets separa argumentos con `;` y lee la coma como marca decimal. El
`SUMPRODUCT` de un argumento da el mismo total sin separadores, así que el texto de la
fórmula vale en cualquier idioma; un test recorre el grid y exige que ninguna fórmula
lleve `,` ni `;`.

Escritura (`_write_summary_region`): si la fila 12 columna J no dice `RESUMEN MES`, la
pestaña está en la geometría vieja y se limpia desde `J2` (una sola vez); a partir de ahí
solo `J12:K30`. El rango de formato de dinero empieza en `K4`, de modo que los importes
del dueño también se ven como euros.

`style._right_hand_panel` repinta las tres bandas y `layout_requests` fusiona
`J12:K12` y `J20:K20` además de las bandas de la fila 2. Los colores salen de la captura
que mandó el dueño (`2026-11-24`, OCR con `tesseract -l spa`): cada bloque lleva una
banda de título **oscura** con letras blancas encima de una banda de cabecera más clara
del mismo tono —`INGRESOS` `9BBB59` sobre `92D050`, `RESUMEN MES` `4F81BD` sobre
`548DD4`, `SALDO CUENTAS` `C0504D` sobre `FABF8F`— y el amarillo `FFDE00` desapareció.
De la captura también salieron los rótulos `CANTIDAD` en la cabecera de saldos y el
`TOTAL` en mayúsculas de la última fila, y la alineación: conceptos y cabeceras a la
izquierda, importes centrados (en la captura los seis saldos giran alrededor de la misma
x, no empiezan en la misma) y títulos de banda centrados sobre `J:K`.

El resumen nació sin fondo («no tiene acento propio», pedido del 2026-11-22) y el
2026-11-23 el dueño pidió **amarillo en el título y la cabecera**, con las letras de
`CONCEPTO`/`CANTIDAD` en blanco como la cabecera de gastos comunes. El primer intento,
`FFFF99`, le pareció poco amarillo, así que `LIGHT_YELLOW` es ahora `FFDE00` (amarillo
cálido y saturado) y se usa en los dos sitios que pintan la banda: el `repeatCell` del
panel y el de `layout_requests`, para que el merge no la devuelva a blanco. El título
conserva las letras negras.

Después el dueño señaló una fila de gasto concreta de `2026-11` (`DELICIES ALBAL`,
fila 13) como la que quería de alto y pidió que **todas las filas de las tablas** fueran
así. Esa fila medía 28 px porque caía sobre una fila de cabecera del panel: el alto no
era uniforme, sino 17 px de cuerpo con 28 en 2-3, 12-13 y 20-21. Ahora
`row_height_requests` fija **28 px en todas las filas** y `header_height_requests`
desaparece: no queda nada que diferenciar.

Después el dueño pidió que **las celdas de contenido también se ensanchen**: el ancho
del mayor elemento más un poco de holgura. `layout.column_widths` lo calcula por columna
(`B`, `C`, `D`, `E`, `G`, `H`, `J`, `K`; los separadores `A`, `F` e `I` no se tocan) con
`7,8 px` por carácter + `28 px` de margen, redondeado a 5 px. Tres límites lo hacen
usable:

- **Suelo** de 90 px para cualquier columna.
- **Suelos propios** en las columnas de importe (`E`, `H`, `K`, 130 px) y en `J`
  (200 px): el contenido de hoy es corto, pero un `-1.735,98 €` o un importe tecleado
  por el dueño necesita el hueco.
- **Techo** de 400 px: un concepto de transferencia de 121 caracteres pedía 975 px y
  habría empujado la tabla fuera de la pantalla; el texto se conserva, la columna para
  de crecer.

El catálogo de gastos comunes es de dos niveles y también se tabula: `Mercadona`,
`Consum`, `Otros`, `Petsitter`, los `Día`, `Zooplus`, `Agua`, `Gas`, `Limpieza`, `Luz`,
`Menaje`, `HBO`, `Spotify`, los `AVE día`, `Motos alquiler`, `Taxi`, `VTC`, `Coche`, los
`Gasolina día`, `Lavado`, `Parking`, `Peajes` y `Taller` van con 24 pt de sangría (35
filas) y los siete `Día` un escalón más adentro (48 pt, `SHARED_DEEP_INDENT_POINTS`),
mientras sus encabezados —`Alimentación`, `Gatos`, `Piso`, `Streaming`,
`Transporte`…— quedan al ras. `layout.SHARED_SECTION_HEADERS` es el conjunto que no se
indenta y `shared_sub_item_rows()` deriva el resto del catálogo, así que una línea nueva
solo necesita añadirse a `CATEGORIES`.

`LayoutWriter` lo aplica en las dos rutas, después de escribir: lee `get_all_values()`
(valores ya renderizados, así una fórmula no cuenta por su texto) y manda en un mismo
`batch_update` los `repeatCell` de la tabulación y los `updateDimensionProperties` del
ancho (`_apply_geometry`). Anchos medidos en `2026-11` tras
aplicarlo: `B` 110, `C` 110, `D` 400, `E` 130, `G` 200, `H` 130, `J` 200, `K` 130.

Tests: `tests/unit/test_layout_grid.py` (31), `tests/unit/test_layout_writer.py` (35,
incluye migración desde la geometría vieja y que `K4:K10` sobrevive a los refrescos) y
`tests/unit/sheets/test_style.py` (7, payload puro: geometría, colores de la captura y
ningún request escribe valores).

Aplicado a `2026-11` por API: se deshizo el merge viejo `J8:K8`, se reescribió el panel
con el mismo camino que usa el refresco, se fusionaron los títulos nuevos y se aplicó
`format_requests` + `layout_requests` + alto de fila. Verificado leyendo `J1:L32`: la
geometría coincide con la tabla de arriba y los merges son `B2:E2`, `G2:H2`, `J2:K2`,
`J12:K12`, `J20:K20`. Los saldos que ya había (ING 868,70; Revolut 13,46; MyInvestor y
Sabadell sin importe) se conservaron; `K4:K10` queda vacío a la espera de que el dueño
teclee los ingresos, así que `Ingresos totales` marca 0 hasta entonces.

Pendiente:

1. Llamar a `format_requests`/`layout_requests` desde `layout.py` al crear una pestaña;
   hoy diciembre nacería con el panel nuevo pero sin el estilo del libro.
2. Comando `banking style --sheet 2026-11` (idempotente) para no depender de un script
   suelto.
3. Extender el estilo al resto de pestañas cuando el dueño lo apruebe (D3).
