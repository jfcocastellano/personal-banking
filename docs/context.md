# Documento de Contexto del Proyecto

> **Fuente de verdad del proyecto.** Este documento debe mantenerse actualizado ante cualquier cambio de requisitos, stack o decisiones de diseño.
>
> Última actualización: 2026-11-04

---

## Estado actual de la implementación

Las secciones 1–5 describen el **contrato objetivo** del proyecto. No hay que confundirlo con lo ya construido:

| Iteración | Alcance | Estado |
|-----------|---------|--------|
| IT1 | Skeleton del proyecto y pipeline CI | Implementada |
| IT2 | Conector Enable Banking (ING) | Implementada |
| IT3 | Writer de Google Sheets | Implementada |
| IT4 | Pipeline ING → Sheets (MVP) | Implementada |
| IT5 | Multi-banco con resiliencia parcial | Implementada |
| IT6 | Notificación de errores por email | Implementada |
| IT7 | Scheduler en GitHub Actions | Implementada (2026-10-17) |

Las siete iteraciones del roadmap están implementadas: el scheduler automático (UC1), el disparo manual vía `workflow_dispatch` (UC2) y la notificación por email ante fallo (UC3) viven ya en el repositorio. La planificación vive en `docs/roadmap.md`.

**Observabilidad**
Implementada en `src/banking/logging_config.py`. El entry point de la CLI instala sobre el logger raíz el formato exigido por la constitución (`%(asctime)s %(levelname)s %(name)s: %(message)s`) y resuelve el nivel desde la variable de entorno `LOG_LEVEL` (por defecto `INFO`; un valor no reconocido cae a `INFO`, para que un error de tipeo no aborte una sincronización). Importar `banking` nunca reconfigura el logging de la aplicación anfitriona.

**Despliegue y operación (IT7)**
El scheduler vive en `.github/workflows/sync.yml`, separado del pipeline de CI (`.github/workflows/ci.yml`):

- **Disparadores**: `schedule` con una única entrada `cron: "0 6 * * *"` (06:00 UTC ≈ 08:00 Madrid en verano) y `workflow_dispatch` sin parámetros. Ni `push` ni `pull_request` disparan la sincronización. La hora se cambia editando esa línea del cron, que es el único punto de configuración horaria; los workflows programados solo se ejecutan desde `main`.
- **Ejecución**: job único `ubuntu-latest`, Python 3.12, `timeout-minutes: 10`, `permissions: contents: read` y `concurrency: banking-sync` con `cancel-in-progress: false` (serializa las ejecuciones para que nunca haya dos escrituras simultáneas en la misma pestaña).
- **Sin lógica de CI en el código**: el workflow ejecuta `python -m banking daily`, el mismo comando que en local.
- **Configuración**: los 14 secretos de GitHub se validan como primer paso (fallo en menos de un minuto, nombrando el ausente y sin llamar a ninguna API, para no gastar la cuota PSD2 de 4 peticiones/cuenta/día) y se materializan en los dos mecanismos que usa el código: el `.env` cifrado del `SecretStore` (11 claves, vía `python -m banking secrets set`) y el fichero de firma RSA de Enable Banking (`eb-config.json` + PEM en `$RUNNER_TEMP`, fuera del workspace).
- **Resultado**: el estado de la ejecución coincide con el exit code del proceso (`0`-`4`, ver tabla de notificaciones) y cada ejecución publica un resumen en su página con bancos procesados, movimientos escritos, fallos con su motivo y duración total.
- **Primera ejecución real de la pasada diaria fusionada**: 2026-11-07, ejecución [`42366404900`](https://github.com/jfcocastellano/personal-banking/actions/runs/42366404900) (`workflow_dispatch` sobre `main` en `0e1f848`) con `success` en 36 s. Resumen publicado: «Pasada diaria completada: 2/4 bancos — 13 movimientos en la pestaña 2026-11 y 13 filas en la pestaña 2026-11 Gastos (8.99s)», con `status=full_success`, `rows_written=13`, `balance_rows=4` y `balances_reported=2`. MyInvestor y Banco Sabadell quedaron sin sesión PSD2, que es estado quieto y no fallo.
- **Retraso del cron**: en las ejecuciones observadas del 2026-11-01 al 2026-11-06 el `cron: "0 6 * * *"` aterrizó entre las 12:30 y las 14:35 UTC (retraso de 6,5 a 8,5 h por la cola de GitHub). La cuota PSD2 se consume cuando la pasada arranca, no cuando estaba programada, así que dos ejecuciones el mismo día son dos pasadas completas sobre la misma cuota.

Los runbooks de alta de secretos, primera ejecución, rotación de credenciales y re-autorización de sesiones PSD2 caducadas están en `specs/007-scheduler-github-actions/quickstart.md` y, en versión operativa, en la sección IT7 de `quickstart.md`. La reconstrucción completa de las 14 credenciales desde cero (clave maestra, `app_id`/PEM de Enable Banking, flujo de consentimiento PSD2, cuenta de servicio de Google, app password de Gmail y subida a GitHub Secrets) está en `docs/credentials-setup.md`.

---

## 1. Visión y Propósito

**Descripción general**
Proceso automatizado que consulta los movimientos bancarios del mes en curso de cuatro entidades financieras (ING, Revolut, MyInvestor y Banco Sabadell) a través de sus APIs, y los consolida en un documento Google Sheets. El objetivo es disponer de un cuadro de control mensual de ingresos y gastos, actualizado automáticamente sin intervención manual.

**Comportamiento central**
Cada mes tiene su propia pestaña en el Google Sheet (ej. `2026-06`). Durante el mes en curso, cada ejecución sobreescribe el contenido de esa pestaña con todos los movimientos desde el día 1 hasta la fecha de ejecución. Al inicio de un nuevo mes, el proceso crea automáticamente la pestaña correspondiente. Las pestañas de meses anteriores no se modifican y actúan como histórico permanente.

**Entidades bancarias en scope (v1)**
ING, Revolut, MyInvestor, Banco Sabadell.

---

## 2. Usuarios y Casos de Uso

**Usuario**
Un único usuario (el propietario del sistema). No hay autenticación, gestión de sesiones ni roles.

**Casos de uso**

| ID  | Caso de uso                | Disparador                        |
|-----|----------------------------|-----------------------------------|
| UC1 | Sincronización programada  | Scheduler automático (GitHub Actions) |
| UC2 | Sincronización manual      | `workflow_dispatch` en GitHub Actions |
| UC3 | Notificación de error      | Fallo en cualquier punto del proceso  |

UC1 y UC2 ejecutan exactamente el mismo proceso. La única diferencia es quién los dispara.

**Gestión de configuración y secretos**
Las credenciales sensibles (credenciales bancarias, tokens, contraseñas) se almacenan **encriptadas**.

- **Producción (GitHub Actions):** GitHub Secrets, encriptados por GitHub.
- **Desarrollo local:** fichero `.env` excluido de control de versiones. Los valores sensibles se almacenan encriptados con AES-256 (librería `cryptography`). La clave maestra de desencriptación se almacena como variable de entorno real del sistema operativo, nunca dentro del fichero `.env`.

**Notificaciones**
En caso de error, el sistema envía **un único email agregado** al propietario con el detalle del fallo: los bancos que fallaron con su motivo y los que sí se sincronizaron. No hay notificación en caso de éxito.

El email se envía mediante Gmail SMTP (`smtplib` de la stdlib, sin dependencias nuevas) dentro del flujo de `python -m banking daily` y del de `python -m banking sync`, antes de devolver el código de salida. La configuración son cinco claves del `SecretStore`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (contraseña de aplicación de Gmail) y `NOTIFY_EMAIL_TO`. Si falta cualquiera de ellas, la notificación se omite con un `WARNING` y el código de salida del desenlace no cambia. Las reglas de envío son las mismas para los dos comandos: correo en fallo parcial, fallo total y fallo de escritura en Sheets; nunca en éxito completo ni cuando todos los bancos están sin sesión PSD2.

**Comandos**

| Comando | Qué escribe | Argumentos |
|---|---|---|
| `python -m banking daily` | las dos pestañas del mes en curso (`YYYY-MM` cruda y `YYYY-MM Gastos` de layout) en una sola pasada | ninguno; el mes es siempre el de ejecución |
| `python -m banking sync` | solo la pestaña cruda `YYYY-MM` | ninguno |
| `python -m banking layout` | solo la pestaña `YYYY-MM Gastos` | `--month YYYY-MM` opcional |

`banking daily` es la pasada diaria única (feature 016) y es lo que corre el scheduler de IT7 desde entonces: un solo proceso que consulta cada banco **una vez** para movimientos y **una vez** para saldo, y escribe las dos pestañas con ese mismo conjunto de movimientos. Esa es la decisión de arquitectura: no se encadenan `sync` y `layout`, porque entre los dos harían 6 GET por cuenta (2 de `sync` y 4 de `layout`, cada etapa resolviendo antes la sesión) y leerían los movimientos dos veces; la pasada diaria hace 2 llamadas de datos y 2 consultas de sesión, es decir 4 GET por cuenta más paginación. El margen frente al límite PSD2 de 4 peticiones por cuenta y día **no está verificado**, porque no está claro si Enable Banking cuenta la consulta de sesión contra ese límite. `sync` y `layout` siguen existiendo y no cambian: `sync` queda como corrida cruda suelta y `layout --month` como el camino de backfill de un mes concreto.

Códigos de salida de `banking sync` y de `banking daily` (son idénticos):

| Código | Significado |
|---|---|
| `0` | Ningún banco falló y la hoja quedó escrita (sin email). Incluye los bancos sin sesión PSD2, que se reportan aparte y no cuentan como fallo, y la corrida en la que ninguno tiene sesión, que no escribe nada (`Sincronización omitida` / `Pasada diaria omitida`) |
| `1` | Ningún banco que tenía que sincronizar lo logró — nada escrito; email enviado u omitido |
| `2` | ≥1 banco exitoso pero falló la escritura en Google Sheets (en `daily` el mensaje nombra la etapa: `raw` o `layout`); email enviado u omitido |
| `3` | ≥1 banco exitoso y ≥1 fallo **real**, escritura correcta; email enviado u omitido |
| `4` | **Fallo de entrega del email** (el resumen de la ejecución ya se imprimió) |

`banking layout` **no** comparte esa tabla: tiene la suya, más corta y con otro significado, porque es una herramienta manual de backfill y no un proceso de sincronización.

Códigos de salida de `banking layout`:

| Código | Significado |
|---|---|
| `0` | Pestaña de layout escrita |
| `1` | No se pudo escribir la pestaña (credenciales, permisos, cuota o más de 400 movimientos en el mes) |
| `2` | `--month` inválido |
| `3` | Ningún banco pudo leer movimientos: no se escribió nada, para no vaciar un mes existente |

En los dos comandos un fallo de saldo **no** cambia el código de salida: se informa en la línea del banco y la fila de saldo de ese banco queda sin dato. Lo que decide el código es el resultado de los movimientos.

---

## 3. Constraints Duros

**Ejecución**
- Frecuencia: una vez al día mediante GitHub Actions scheduled workflow.
- Soporte para disparo manual vía `workflow_dispatch` en GitHub Actions.
- El retardo ocasional de hasta ~15 min en workflows programados de GitHub es aceptable.

**Infraestructura**
GitHub Actions (free tier). Las credenciales sensibles se almacenan como GitHub Secrets. No se requiere servidor propio ni hardware adicional.

**Persistencia**
Sin base de datos. Google Sheets es el único almacén de datos.

**Resiliencia**
Si una API bancaria falla, el proceso continúa con las entidades restantes y notifica el fallo parcial por email. No se aborta la ejecución completa. Un banco que todavía no tiene sesión PSD2 se reporta aparte (`SIN SESIÓN PSD2`) y no cuenta como fallo: no hay email ni exit `3` por su causa.

---

## 4. Stack Técnico

**Lenguaje y runtime**
Python 3.12+

**Ejecución e infraestructura**
GitHub Actions. El scheduling lo gestiona el workflow YAML (`schedule: cron`). El disparo manual se expone mediante `workflow_dispatch`. No se necesita librería de scheduling en el código.

**APIs bancarias**
Enable Banking como agregador PSD2. Actúa de intermediario entre el proceso y las entidades (ING, Revolut, MyInvestor), abstrayendo las diferencias entre sus APIs individuales.

> ⚠️ **Riesgos a validar antes de implementar:**
> - Confirmar que Enable Banking soporta las cuatro entidades, especialmente MyInvestor (entidad española de menor tamaño, no garantizado en agregadores PSD2). Banco Sabadell es una entidad grande y su soporte PSD2 vía Enable Banking se da por probable, pero debe verificarse con `GET /aspsps` antes de implementar su conector (mismo patrón que la verificación ya hecha para ING).
> - Las sesiones PSD2 expiran cada 90-180 días y requieren re-autorización manual (flujo browser); no hay refresh automático.
> - El rate limit PSD2 de 4 peticiones/cuenta/día limita a 1 sincronización real por día en testing.

**Enable Banking — detalles técnicos**

| Aspecto | Detalle |
|---------|---------|
| Autenticación | JWT firmado con clave RSA privada (RS256; verificado contra API real 2026-08-09) |
| Flujo de consentimiento | OAuth2/PSD2 browser-based, una sola vez; obtiene `session_id` válido 90-180 días |
| Ciclo de vida de sesión | `session_id` con validez 90-180 días; no existen refresh tokens — al expirar requiere re-autorización manual |
| Límite de tasa PSD2 | Máximo 4 peticiones de información de cuenta por día por cuenta (regulación europea) |
| Filtrado de transacciones | Solo sincronizar `status: BOOK`; ignorar `PDNG` (pendientes) e `INFO` (informativas) |
| Sentido del movimiento | `DBIT` = cargo/gasto; `CRDT` = abono/ingreso |
| Paginación | Parámetro `continuation_key` en el endpoint de transacciones |
| Config local | `~/.config/banca-personal/eb-config.json` (`app_id` + ruta a clave RSA). Los `session_id` (uno por banco) y el resto de secretos se leen del `SecretStore` cifrado, respaldado por el fichero `.env` |

**Google Sheets**
Autenticación mediante cuenta de servicio de Google Cloud (service account). El JSON de credenciales se almacena como GitHub Secret. El Sheet se comparte con el email de la cuenta de servicio. No requiere intervención humana en ninguna ejecución.

**Notificaciones**
Gmail SMTP con contraseña de aplicación (requiere 2FA activo en la cuenta Google). Usando `smtplib` y `email.message` de la librería estándar de Python — cero dependencias de terceros. Envío sobre `SMTP_SSL` (TLS implícito) con un timeout de 30 s.

**Librerías principales**

| Librería         | Propósito                                          |
|------------------|----------------------------------------------------|
| `gspread`        | Integración con Google Sheets, incluida la autenticación con cuenta de servicio vía `service_account_from_dict()` (`google-auth` se usa transitivamente, no se importa directamente — IT3) |
| `httpx`          | Cliente HTTP para Enable Banking API               |
| `cryptography`   | Encriptación AES-256 de secretos locales y firma JWT RSA (RS256, Enable Banking) |
| `PyJWT`          | Generación y serialización de tokens JWT para autenticación Enable Banking (RS256) |
| `pytest`         | Framework de tests                                 |
| `pytest-mock`    | Mocking en tests                                   |
| `ruff`           | Linting y formateo                                 |
| `mypy`           | Type checking estático                             |
| `pip-audit`      | Auditoría de vulnerabilidades en dependencias (gate de CI) |

> El fichero `.env` lo parsea y escribe el propio `SecretStore` (`src/banking/config/secret_store.py`) con la librería estándar: el proyecto **no** usa `python-dotenv`.

**Dependencias de infraestructura externa**
Enable Banking (cuenta y API key necesarias), Google Cloud (proyecto con Sheets API habilitada, service account), cuenta Gmail con 2FA.

---

## 5. Definition of Done

Una feature se considera terminada cuando se cumplen **todos** los siguientes criterios:

**Tests**
- Tests unitarios e integración implementados con `pytest`.
- Las APIs externas (Enable Banking, Google Sheets, Gmail) se mockean en los tests. No se realizan llamadas reales en el pipeline de CI.
- Sin requisito de cobertura numérico. Se cubren las rutas críticas del flujo principal y los casos de error definidos.

**CI verde en GitHub Actions**
El pipeline de GitHub Actions pasa completamente antes de considerar la feature terminada. El pipeline incluye: tests + linting + formateo + type checking.

**Calidad de código**

| Herramienta | Propósito                                           |
|-------------|-----------------------------------------------------|
| `ruff`      | Linting y formateo (reemplaza flake8 + black + isort) |
| `mypy`      | Type checking estático                              |

Cualquier violación de `ruff` o `mypy` rompe el pipeline de CI./
