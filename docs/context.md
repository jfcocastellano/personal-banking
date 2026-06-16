# Documento de Contexto del Proyecto

> **Fuente de verdad del proyecto.** Este documento debe mantenerse actualizado ante cualquier cambio de requisitos, stack o decisiones de diseño.
>
> Última actualización: 2026-06-16

---

## 1. Visión y Propósito

**Descripción general**
Proceso automatizado que consulta los movimientos bancarios del mes en curso de tres entidades financieras (ING, Revolut y MyInvestor) a través de sus APIs, y los consolida en un documento Google Sheets. El objetivo es disponer de un cuadro de control mensual de ingresos y gastos, actualizado automáticamente sin intervención manual.

**Comportamiento central**
Cada mes tiene su propia pestaña en el Google Sheet (ej. `2026-06`). Durante el mes en curso, cada ejecución sobreescribe el contenido de esa pestaña con todos los movimientos desde el día 1 hasta la fecha de ejecución. Al inicio de un nuevo mes, el proceso crea automáticamente la pestaña correspondiente. Las pestañas de meses anteriores no se modifican y actúan como histórico permanente.

**Entidades bancarias en scope (v1)**
ING, Revolut, MyInvestor.

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

> ⚠️ **Riesgo a validar antes de implementar:** confirmar que Enable Banking soporta las tres entidades, especialmente MyInvestor (entidad española de menor tamaño, no garantizado en agregadores PSD2).

**Google Sheets**
Autenticación mediante cuenta de servicio de Google Cloud (service account). El JSON de credenciales se almacena como GitHub Secret. El Sheet se comparte con el email de la cuenta de servicio. No requiere intervención humana en ninguna ejecución.

**Notificaciones**
Gmail SMTP con contraseña de aplicación (requiere 2FA activo en la cuenta Google). Usando `smtplib` de la librería estándar de Python.

**Librerías principales**

| Librería         | Propósito                                          |
|------------------|----------------------------------------------------|
| `gspread`        | Integración con Google Sheets                      |
| `google-auth`    | Autenticación service account                      |
| `httpx`          | Cliente HTTP para Enable Banking API               |
| `python-dotenv`  | Carga de fichero `.env`                            |
| `cryptography`   | Encriptación AES-256 de secretos locales           |
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
