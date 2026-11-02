# Feature: un parcial esperado no es un fallo (bancos sin sesión PSD2)

## Problema

Dos de los cuatro bancos no van a tener sesión PSD2 por causas del proveedor
(Sabadell: `unsupported_response_type` en su `authorize`, § 3.5; MyInvestor: el
login de Inversis devuelve 302→404 sin CORS, § 3.6). Hoy el sync los cuenta como
fallos: exit `3`, workflow rojo y email todos los días. El resultado es que un
fallo real —ING caída mañana— queda indistinguible de la situación normal.

## Decisión

Tres estados por banco, no dos:

| Estado | Significado | ¿Fallo? | Exit | Email |
|---|---|---|---|---|
| `OK` | trajo movimientos | no | 0 | no |
| `NOT_ONBOARDED` | sin sesión PSD2 (centinela inerte) | **no** | 0 | no |
| `FAILED` | tenía sesión y falló | sí | 3 | sí |

`NOT_ONBOARDED` se reconoce por una excepción propia (`BankNotOnboardedError`),
no por el texto del mensaje. Un secreto ausente o vacío **no** es
`NOT_ONBOARDED`: es fallo real, porque el workflow ya exige los 14 secretos y una
ausencia es una rotura de configuración.

## Tareas

- [x] T1 — `BankNotOnboardedError` en el conector, heredando de `ConnectorConfigError` (sin romper a quien ya lo captura)
- [x] T2 — `BankOutcome.not_onboarded` + propiedad `failed`; `_sync_one_bank` clasifica la excepción nueva
- [x] T3 — `_classify` cuenta fallos reales: solo `NOT_ONBOARDED` da `FULL_SUCCESS`
- [x] T4 — Resumen y exit codes del CLI: línea `SIN SESIÓN PSD2`, sin disparar notificación
- [x] T5 — Notificación: los bancos sin sesión se listan aparte y no cuentan como fallo
- [x] T6 — Documentación alineada (§ 3.5, § 3.6, § 6, § 10 y `docs/context.md`)

- [x] T7 — Guarda: si ningún banco tiene sesión no se llama al writer (escribir vacío borraría la pestaña); estado `NOTHING_TO_SYNC`, exit `0`

## Criterios de aceptación

- Con ING y Revolut OK, MyInvestor y Sabadell sin sesión: exit `0`, sin email, resumen con las dos líneas `SIN SESIÓN PSD2`.
- Con un banco con sesión que falla: exit `3` y un email, que menciona también a los bancos sin sesión como contexto.
- Ningún banco aporta datos y hay fallos reales: exit `1`, mensaje que no diga "los 4 bancos fallaron" cuando alguno solo estaba sin sesión.
- Con los cuatro bancos sin sesión: exit `0`, `Sincronización omitida`, y la pestaña del mes sin tocar.
- `ruff check`, `ruff format --check`, `mypy src` y la suite completa en verde.
