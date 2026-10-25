# Quickstart — Layout mensual de contabilidad (IT8)

**Funcionalidad**: `008-monthly-sheet-layout` | **Fecha**: 2026-10-25

Guía de uso y de operación del tab mensual con los tres bloques de la hoja de contabilidad
manual. El día a día es un comando; el resto de esta guía explica qué es automático, qué sigue
siendo tuyo, y los límites que no se pueden sortear.

---

## 0. Requisitos previos

- IT5 desplegado: los cuatro conectores (`python -m banking sync`) y `GOOGLE_SHEET_ID` configurados.
- Las cuatro sesiones PSD2 vigentes. Una sesión caducada no rompe el layout: ese banco aparece
  como fallo en el informe y su bloque queda vacío.
- El mismo permiso de escritura que ya usa el sync (la cuenta de servicio comparte el documento).

---

## 1. Generar el tab del mes

```bash
# Mes en curso
.venv/bin/python -m banking layout

# Un mes concreto
.venv/bin/python -m banking layout --month 2026-09
```

`--month` acepta exactamente `YYYY-MM`. Cualquier otra cosa sale con código 2 sin escribir nada.

---

## 2. Qué se escribe

Dos tabs por mes, y cada uno tiene un único dueño:

| Tab | Dueño | Cuándo se escribe |
| --- | --- | --- |
| `2026-09` | `banking sync` | cada corrida reemplaza el tab completo (sin cambios) |
| `2026-09 Gastos` | `banking layout` | la primera corrida crea todo; las siguientes reescriben **solo** el bloque de gastos |

La columna A queda vacía como separador, igual que en la hoja original. Los tres bloques
comparten las filas 2 y 3 (títulos y encabezados) y después cada uno avanza por su cuenta:

| Bloque | Celdas | Contenido |
| --- | --- | --- |
| Títulos (combinados) | `B2:E2`, `G2:H2`, `J2:K2` | `GASTOS`, `GASTOS COMUNES`, `INGRESOS` |
| Encabezados (fila 3) | `B3:E3`, `G3:H3`, `J3:K3` | `FECHA` `BANCO` `DESCRIPCIÓN` `IMPORTE` · `CATEGORÍA` `TOTAL` · `CONCEPTO` `IMPORTE` |
| Gastos individuales | `B4:E403` | un movimiento por fila, ordenado por fecha y banco |
| Gastos comunes | `G4:G52` etiquetas, `H4:H52` importes a mano, `H53` total | catálogo de 49 categorías y `=SUM(H4:H52)` |
| Resumen | `J4:K6` | `Ingresos` `=SUMIF(…,">0",…)`, `Gastos` `=SUMIF(…,"<0",…)`, `Total` `=K4+K5` |
| Saldos | `J8` título, `J9:K9` encabezados, `J10:J13` cuentas, `J14` total, `J15` fecha | `=SUM(K10:K13)` |

Los totales son **fórmulas**, no números: si corregís un importe a mano en la columna E, el
resumen se recalcula solo.

---

## 3. Qué es automático y qué no

| Bloque | Automático | Manual |
| --- | --- | --- |
| Gastos individuales (`B:E`) | sí: lo que devuelvan ING, Revolut, MyInvestor y Sabadell, cuatro columnas sin divisa | corregir el concepto |
| Gastos comunes (`G:H`) | solo el catálogo de 49 categorías, con los importes vacíos | el importe de cada categoría |
| Resumen (`J:K`) | ingresos, gastos y neto por fórmula | nada |
| Saldos cuentas | una fila por conector con el saldo que informa el banco | nada |

Hoy solo ING, Revolut y MyInvestor aportan movimientos: el conector de Sabadell existe pero su
sesión PSD2 no se pudo obtener (`docs/credentials-setup.md` § 3.5). Cuando esa credencial exista,
Sabadell aparecerá como una fila más; las categorías del bloque central se seguirán asignando a
mano, porque ninguna API las informa.

**N26 no aparece**: está en la hoja original pero el proyecto no tiene conector de N26. Agregarlo
es replicar el patrón de los otros cuatro (una clave `ENABLE_BANKING_SESSION_ID_N26` y una clase).

---

## 4. Límites que conviene conocer antes de usarlo

- **El saldo no es histórico.** PSD2 informa el saldo del momento en que se consulta. Si corrés el
  comando el día 12, el panel muestra el saldo del día 12, no el del último día del mes. La fila
  `Saldos al` imprime la fecha de referencia más reciente que informen los bancos, o
  `sin dato de referencia` si ninguno la informa. El snapshot diario para tener el cierre real
  depende del scheduler (`specs/007`).
- **Lo que edites dentro de `B4:E403` se sobrescribe** en la siguiente corrida. Lo que edites en
  `G:H` y `J:K` se respeta. Esa es toda la garantía, y es deliberada.
- **Tope de 400 movimientos por mes.** Al superarlo el comando falla en vez de truncar en silencio.
- **Sin anchos de columna.** El formato aplicado es negrita en títulos y encabezados y formato de
  moneda; los anchos hay que ajustarlos a mano una vez por tab.

---

## 5. Códigos de salida

| Código | Significado |
| --- | --- |
| `0` | tab escrito |
| `1` | no se pudo escribir el tab (credenciales, permisos, cuota, o más de 400 movimientos en el mes) |
| `2` | `--month` inválido |
| `3` | ningún banco pudo leer movimientos: no se escribió nada, para no vaciar un mes existente |

Un fallo de saldo **nunca** cambia el código de salida: se informa en la línea del banco y el resto
del layout se genera igual.

---

## 6. Verificación manual

1. `.venv/bin/python -m banking layout --month <mes con datos>`
2. Abrir `<mes> Gastos`: los tres bloques deben estar en las posiciones del § 2.
3. Escribir un importe a mano en una celda de `H` y volver a correr el comando.
4. Confirmar que el importe sigue ahí y que el resumen no cambió por eso.
5. Editar un importe en `E` y confirmar que `Ingresos`, `Gastos` y `Total` se recalculan.

Si el paso 4 falla, es un defecto del writer y no del formato: el bloque `G:H` no debe recibir
escrituras en la ruta de actualización.
