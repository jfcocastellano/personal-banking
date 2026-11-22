# banca-personal

Automatización de finanzas personales: lee los movimientos bancarios por PSD2 y los deja
en una hoja de Google con la estructura de la contabilidad mensual que se lleva a mano.

Corre solo, todos los días, sin intervención. Si un banco falla, avisa por email y sigue
con los demás.

## Qué hace

```text
Enable Banking (PSD2)  →  conectores  →  pestaña del mes  `2026-11`
                                            ├─ gastos individuales  B4:E403
                                            ├─ gastos comunes       G:H   (se edita a mano)
                                            └─ resumen + saldos     J:K
```

Una sola pasada por banco alimenta una sola pestaña: el layout de contabilidad de
mes, con fecha, banco, descripción e importe en `B:E`.

| Banco | Estado |
| --- | --- |
| ING España | Activo |
| Revolut | Activo |
| MyInvestor | Conector listo, **sin sesión PSD2** (el login de Inversis no responde) |
| Banco Sabadell | Conector listo, **sin sesión PSD2** (`unsupported_response_type`) |

Un banco sin sesión se reporta como `SIN SESIÓN PSD2` y no cuenta como fallo: no hay
email ni exit code de error por su causa.

## Cómo se usa

Local, con la `BANKING_MASTER_KEY` y la sesión PSD2 ya configuradas:

```bash
python -m banking daily                      # lo que corre el cron: las dos pestañas
python -m banking sync                       # solo la pestaña cruda
python -m banking layout --month 2026-09     # rehacer el layout de un mes concreto
python -m banking secrets set …              # gestionar secretos cifrados
```

Sin claves en la máquina, el mismo trabajo se lanza desde Actions:
`Actions → Sync diaria → Run workflow` (`workflow_dispatch`, sin parámetros).

El cron corre a las **06:00 UTC** (`0 6 * * *`) y vive en `.github/workflows/sync.yml`.

Pasos completos, permisos de PSD2 y despliegue desde cero: [`quickstart.md`](quickstart.md).

## Estructura

```text
src/banking/
  connectors/     enable_banking.py (cliente PSD2) + un módulo por banco
  sheets/         writer (gspread) + layout.py (geometría de la pestaña de gastos)
  cli/            sync, daily, layout, secrets
  config/         almacén de secretos cifrados
  sync.py         orquestación: bancos → filas, exit codes, email
tests/unit/       374 tests, sin red: todo se prueba contra dobles
specs/            una spec por iteración (contrato, no estado)
odd/tasks/        trabajo posterior a IT8, un fichero por unidad
docs/             context.md (fuente de verdad), roadmap.md, credentials-setup.md
```

## Desarrollo

Requiere **Python ≥ 3.12**.

```bash
uv venv --python 3.12 .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt && .venv/bin/pip install -e .

.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy src           # strict
```

CI (`.github/workflows/ci.yml`) corre en cada push exactamente eso, más `pip-audit`.

## Límites conocidos

- **La categoría de los movimientos es manual.** Ni ING España ni Revolut informan
  `merchant_category_code` por PSD2 (`0/44` y `0/9` medidos en producción), y
  `bank_transaction_code` solo trae el canal de la operación. El catálogo de `G:H` se
  llena a mano; hay un sondeo en el log que documenta la ausencia.
- **Los saldos son una foto**, no un histórico: PSD2 no expone saldos pasados, así que
  el mes anterior deja de actualizarse cuando cambia el mes.
- **Cuota PSD2**: 4 `GET` por cuenta y día. Una pasada manual el mismo día consume cupo
  de la del cron.
- **La pestaña del mes no se reescribe entera**: `B3:E403` y `J:K` son de la máquina;
  lo que edites en `G:H` sobrevive.

## Privacidad

Los logs de Actions son públicos para quien tenga acceso al repositorio y **nunca**
contienen importes, fechas de operación, `remittance_information`, referencias ni
nombres de contrapartes. Lo único que se registra de una transacción son los *nombres*
de sus campos y el recuento de cuántos traen valor; la frontera está en
`_FieldProbe`/`_BankTransactionCodeProbe`, en un solo sitio y con tests que la vigilan.

Los secretos (clave RSA de Enable Banking, sesiones PSD2, cuenta de servicio de Google,
contraseña de aplicación de Gmail) viven cifrados con `BANKING_MASTER_KEY` en local y
como GitHub Secrets en CI. Ver [`docs/credentials-setup.md`](docs/credentials-setup.md).

## Documentación

| Documento | Para qué |
| --- | --- |
| [`docs/context.md`](docs/context.md) | **Fuente de verdad**: qué está construido, decisiones, campos reales de la API |
| [`quickstart.md`](quickstart.md) | Puesta en marcha y operación |
| [`docs/roadmap.md`](docs/roadmap.md) | Intención y trabajo no empezado |
| [`odd/tasks/`](odd/tasks) | Unidades de trabajo posteriores a IT8, con su evidencia |
| [`specs/`](specs) | Contrato de cada iteración |
| [`AGENTS.md`](AGENTS.md) | Contexto para agentes que trabajen en el repo |
