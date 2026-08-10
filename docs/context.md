# Documento de Contexto del Proyecto

> **Fuente de verdad del proyecto.** Este documento debe mantenerse actualizado ante cualquier cambio de requisitos, stack o decisiones de diseño.
>
> Última actualización: 2026-08-10

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
En caso de error, el sistema envía un email al propietario con el detalle del fallo. No hay notificación en caso de éxito.

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
Si una API bancaria falla, el proceso continúa con las entidades restantes y notifica el fallo parcial por email. No se aborta la ejecución completa.

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
| Config local | `~/.config/banca-personal/eb-config.json` (`app_id` + ruta a clave RSA); `eb-session.json` (session_id activo) |

**Google Sheets**
Autenticación mediante cuenta de servicio de Google Cloud (service account). El JSON de credenciales se almacena como GitHub Secret. El Sheet se comparte con el email de la cuenta de servicio. No requiere intervención humana en ninguna ejecución.

**Notificaciones**
Gmail SMTP con contraseña de aplicación (requiere 2FA activo en la cuenta Google). Usando `smtplib` de la librería estándar de Python.

**Librerías principales**

| Librería         | Propósito                                          |
|------------------|----------------------------------------------------|
| `gspread`        | Integración con Google Sheets, incluida la autenticación con cuenta de servicio vía `service_account_from_dict()` (`google-auth` se usa transitivamente, no se importa directamente — IT3) |
| `httpx`          | Cliente HTTP para Enable Banking API               |
| `python-dotenv`  | Carga de fichero `.env`                            |
| `cryptography`   | Encriptación AES-256 de secretos locales y firma JWT RSA (RS256, Enable Banking) |
| `PyJWT`          | Generación y serialización de tokens JWT para autenticación Enable Banking (RS256) |
| `pytest`         | Framework de tests                                 |
| `pytest-mock`    | Mocking en tests                                   |
| `ruff`           | Linting y formateo                                 |
| `mypy`           | Type checking estático                             |

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
