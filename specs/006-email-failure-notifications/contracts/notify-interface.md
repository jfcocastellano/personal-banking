# Contrato: Notificador de email (`banking.notify`)

Interfaz Python interna, consumida por la capa CLI (`banking.cli.sync`). Formaliza FR-001 a FR-009
de la spec. El notificador es el único componente que toca SMTP; la capa CLI decide cuándo
invocarlo y traduce el resultado a exit codes.

## Tipos exportados

```python
class DeliveryStatus(enum.Enum):
    SENT = "sent"          # envío completado
    SKIPPED = "skipped"    # configuración ausente/incompleta — no se intentó (FR-007)
    FAILED = "failed"      # envío intentado y fallido (FR-006)


@dataclasses.dataclass(frozen=True)
class EmailConfig:
    host: str          # SMTP_HOST
    port: int          # SMTP_PORT (entero válido)
    user: str          # SMTP_USER (remitente = cuenta autenticada)
    password: str      # SMTP_PASSWORD — nunca en logs ni mensajes (FR-008)
    to_address: str    # NOTIFY_EMAIL_TO
```

## Clase pública: `EmailNotifier`

```python
class EmailNotifier:
    def __init__(
        self,
        store: SecretStore | None = None,
        smtp_factory: Callable[[EmailConfig], smtplib.SMTP] | None = None,
    ) -> None: ...

    def notify_failure(
        self,
        outcomes: list[BankOutcome],
        sheets_error: str | None,
        tab_name: str,
        duration_seconds: float,
    ) -> DeliveryStatus: ...
```

**Constructor**:
- `store`: opcional. Si se omite, `SecretStore()` (mismo patrón que `SheetsWriter`, IT3). Los tests
  que necesiten configuración inyectan un `Mock(spec=SecretStore)` o un `SecretStore` sobre un
  `.env` temporal.
- `smtp_factory`: opcional. Fábrica que recibe la `EmailConfig` resuelta y devuelve el cliente SMTP.
  Por defecto crea `smtplib.SMTP_SSL(config.host, config.port, timeout=_SMTP_TIMEOUT_SECONDS)`
  (30s, constante de módulo — SLO de entrega < 60s). Los tests **siempre** inyectan una fábrica que
  devuelve `Mock(spec=smtplib.SMTP)` — cero conexiones reales (Principio III, FR-010).

**Método `notify_failure`**:
- **Entrada**: el contexto de la ejecución fallida (ver `data-model.md` → Contexto de fallo).
  `outcomes` vacío + `sheets_error` no nulo = fallo de Sheets puro; `outcomes` con fallos +
  `sheets_error` no nulo = caso combinado (un solo email con ambos, FR-002).
- **Salida**: `DeliveryStatus` — nunca lanza excepciones hacia el CLI (FR-006).
- **Comportamiento**:
  1. Carga la configuración (`_load_config`): si falta cualquiera de las cinco claves o el puerto no
     es entero válido → log `WARNING` (sin secretos) y devuelve `SKIPPED` (FR-007).
  2. Construye el `EmailMessage` (asunto clasificado por desenlace + cuerpo texto plano en español,
     tabla de `research.md` Decisión 7).
  3. Abre la conexión con la fábrica, hace `login(user, password)`, `send_message(msg)` y `quit()`.
     Cualquier excepción en esta fase → log `ERROR` (tipo de excepción + motivo, sin secretos) y
     devuelve `FAILED` (FR-006). El socket se cierra aunque `send_message` lance.
  4. Éxito → log `INFO` (destinatario, desenlace, duración del envío) y devuelve `SENT`.

## Clasificación del asunto (FR-005)

| Condición | Asunto |
|---|---|
| `sheets_error is None` y ≥1 outcome fallido y ≥1 exitoso | `Sincronización parcial: <k>/4 bancos — fallo en <tab_name>` |
| `sheets_error is None` y todos fallidos | `Sincronización fallida: los 4 bancos fallaron — <tab_name>` |
| `sheets_error` no nulo y sin fallos de banco | `Sincronización fallida: error escribiendo en Google Sheets — <tab_name>` |
| `sheets_error` no nulo y con fallos de banco | `Sincronización fallida: error escribiendo en Google Sheets (con fallos de banco) — <tab_name>` |

## Cuerpo del email (FR-005, texto plano, español)

```text
La sincronización bancaria terminó con errores.

Fecha: <YYYY-MM-DD HH:MM>
Pestaña: <tab_name>
Duración: <T>s

Bancos:
  - ING España: <n> movimientos
  - Revolut: FALLÓ — <motivo>
  - ...

ERROR (Sheets): <motivo>        ← solo si sheets_error no es None (causa principal)
```

Restricciones: ningún campo incluye credenciales, contraseñas, tokens, JWT, `session_id` completo
ni JSON de cuenta de servicio (FR-008). Los motivos ya llegan sanitizados desde los conectores
(contrato IT5, FR-004).

## Claves de configuración (SecretStore)

`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO` — todas obligatorias para
enviar; la ausencia de cualquiera degrada a `SKIPPED` (FR-007). Ver `research.md` Decisión 3.

## Restricciones transversales

- `notify.py` no llama a `print()` — solo `logging` (Anti-patrón #6).
- Sin dependencias de terceros: `smtplib` + `email` (stdlib) (Anti-patrón #10).
- Sin estado entre ejecuciones: sin deduplicación, sin reintentos, sin encolamiento (spec §
  Clarifications y § Suposiciones).
- La contraseña SMTP nunca se interpola en logs, mensajes ni emails (Principio IV, FR-008).

## Verificación de contrato (tests, FR-011)

`tests/unit/test_notify.py` con `Mock(spec=smtplib.SMTP)`:
- **Fallo parcial** → `SENT`, asunto "Sincronización parcial", cuerpo con banco fallido + motivo y
  exitosos con recuento.
- **Fallo total** → `SENT`, asunto "los 4 bancos fallaron", cuerpo con los cuatro motivos.
- **Fallo de Sheets** → `SENT`, asunto de Sheets, cuerpo con `ERROR (Sheets): <motivo>`.
- **Caso combinado** → `SENT`, un solo email con causa Sheets + fallos de banco.
- **Éxito no notifica** → el notificador no se invoca (verificado en `test_cli_sync.py`).
- **Fallo del envío** → `FAILED` por cada error SMTP (`smtplib.SMTPException`, `OSError`, ...), sin
  excepción propagada, socket cerrado.
- **Configuración ausente** → `SKIPPED` por cada clave faltante y por puerto no entero, sin
  conexión SMTP.
- **Sin secretos** → ni el asunto ni el cuerpo contienen la contraseña ni el usuario.
