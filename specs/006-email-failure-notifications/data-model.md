# Fase 1: Modelo de Datos — Notificación de Errores por Email

Todas las entidades nuevas son estructuras de datos puras en memoria (dataclass `frozen=True` y
`enum.Enum`, sin persistencia, sin estado entre ejecuciones), consistente con el Principio VII (sin
base de datos ni capa de persistencia) y con la decisión clarificada de no deduplicar entre
ejecuciones.

## Tipos existentes reutilizados (sin cambios de forma)

### `SyncSummary` / `BankOutcome` / `OverallStatus` (IT5)

Definidos en `banking.sync`. El notificador los consume como entrada de solo lectura; esta
iteración no modifica su estructura (FR-009). Ver `specs/005-multi-bank-resilient-sync/data-model.md`.

### `SecretStore` (IT1)

Definido en `banking.config.secret_store`. Fuente de la configuración SMTP; no se modifica.

## `EmailConfig` (nuevo)

Configuración de notificación resuelta, producida por `_load_config()` a partir del SecretStore.
Estructura pura sin comportamiento.

| Campo | Tipo | Notas |
|---|---|---|
| `host` | `str` | Servidor SMTP (p. ej. `smtp.gmail.com`) — clave `SMTP_HOST` |
| `port` | `int` | Puerto SMTP (p. ej. `465`) — clave `SMTP_PORT`, parseada a entero |
| `user` | `str` | Cuenta autenticada y remitente — clave `SMTP_USER` |
| `password` | `str` | Contraseña de aplicación — clave `SMTP_PASSWORD`; NUNCA se registra en logs ni se interpola en mensajes (FR-008, Principio IV) |
| `to_address` | `str` | Destinatario — clave `NOTIFY_EMAIL_TO` |

Invariante: una `EmailConfig` existe solo si las cinco claves están presentes y `port` es un entero
válido; en caso contrario `_load_config()` devuelve `None` (→ `DeliveryStatus.SKIPPED`, FR-007).

## `DeliveryStatus` (nuevo, `enum.Enum`)

Resultado de la entrega de una notificación, devuelto por `EmailNotifier.notify_failure()`
(`research.md` Decisión 4).

| Valor | Significado | Efecto en el exit code del CLI |
|---|---|---|
| `SENT` | El email se envió completando la interacción SMTP | Ninguno — el desenlace de sincronización manda |
| `SKIPPED` | Configuración ausente/incompleta; el email no se intentó (aviso en logs, FR-007) | Ninguno — no es un fallo de entrega |
| `FAILED` | El envío se intentó y falló (error en logs, FR-006) | Exit code `4` |

## `EmailNotifier` (nuevo, componente de salida)

Clase del módulo `banking.notify`. No es una entidad de dominio sino el componente que construye y
envía el email; su contrato formal vive en `contracts/notify-interface.md`.

| Miembro | Tipo | Notas |
|---|---|---|
| `__init__(store, smtp_factory)` | `(SecretStore \| None, Callable[[EmailConfig], smtplib.SMTP] \| None) -> None` | DI de configuración y transporte; por defecto `SecretStore()` y `SMTP_SSL` con timeout de módulo |
| `notify_failure(...)` | `(...) -> DeliveryStatus` | Único método público; nunca lanza excepciones hacia el CLI |

## Contexto de fallo (parámetros de `notify_failure`, no una clase)

El notificador recibe el contexto de la ejecución fallida como parámetros tipados, extraídos por la
capa CLI del `SyncSummary` o de la excepción correspondiente:

| Parámetro | Tipo | Notas |
|---|---|---|
| `outcomes` | `list[BankOutcome]` | Desenlace por banco; en fallo de Sheets puro puede estar vacío |
| `sheets_error` | `str \| None` | Motivo del fallo de escritura; `None` si Sheets tuvo éxito |
| `tab_name` | `str` | Pestaña `YYYY-MM` destino (o la que se hubiera usado) |
| `duration_seconds` | `float` | Duración de la ejecución; `0.0` si no llegó a medirse |

De estos parámetros deriva la clasificación del asunto (fallo parcial / total / Sheets / combinado)
según la tabla de `research.md` Decisión 7.

## Excepciones del pipeline (extendidas, retrocompatible)

`AllBanksFailedError` y `SheetsSyncError` (`banking.sync`) ganan atributos opcionales para que la
notificación consuma contexto estructurado sin reinterpretar texto (FR-009; `research.md` Decisión 6):

| Atributo | Tipo | Rellenado por `run_sync()` cuando |
|---|---|---|
| `outcomes` | `list[BankOutcome] \| None` | Lanza `AllBanksFailedError` (los 4) o `SheetsSyncError` (los obtenidos antes del fallo de escritura) |
| `tab_name` | `str \| None` | En ambos lanzamientos; la pestaña destino (o la que se hubiera usado) |

El mensaje `str(exc)` de ambas no cambia: los tests y consumidores de IT5 siguen funcionando sin
modificación. `None` significa "contexto no disponible" (invocador antiguo) y activa el fallback
defensivo del notificador.

## Email de notificación (artefacto, no entidad)

Mensaje `email.message.EmailMessage` construido por el notificador y descartado tras el envío — no
se persiste ni se encola (sin reintentos, Suposiciones de la spec):

| Cabecera / parte | Valor |
|---|---|
| `From` | `EmailConfig.user` (cuenta autenticada) |
| `To` | `EmailConfig.to_address` |
| `Subject` | Clasificado por desenlace, en español — tabla de `research.md` Decisión 7 |
| Cuerpo | `text/plain; charset="utf-8"` — fecha, pestaña, duración, línea por banco, causa principal si es fallo de Sheets |

Restricción transversal: ni el asunto, ni el cuerpo, ni las cabeceras incluyen credenciales,
contraseñas, tokens, JWT, `session_id` completo ni JSON de cuenta de servicio (FR-008).
