# 022 — Replicar el estilo del libro de gastos en todas las hojas

Estado: **bloqueada en acceso**, especificación cerrada. Origen: `Gastos 2026 hasta 31
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
