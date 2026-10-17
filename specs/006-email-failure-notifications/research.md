# Fase 0: Investigación — Notificación de Errores por Email

## Decisión 1: Canal de envío — `smtplib` de la librería estándar, sin dependencias nuevas

**Decisión**: El envío se implementa con `smtplib.SMTP_SSL` (puerto 465) y
`email.message.EmailMessage` de la librería estándar de Python. No se añade ninguna dependencia de
terceros a `requirements.txt`.

**Rationale**: `docs/context.md` (stack técnico, Notificaciones) ya ratifica "Gmail SMTP con
contraseña de aplicación... Usando `smtplib` de la librería estándar de Python", y el Principio VII
de la constitución ordena preferir stdlib cuando la capacidad es equivalente — lo es: Gmail SMTP
con contraseña de aplicación es autenticación LOGIN/PLAIN simple sobre TLS implícito, sin OAuth ni
XOAUTH2. Añadir `yagmail` o similar introduciría una dependencia que hay que pinear, auditar con
`pip-audit` y mantener, sin ningún beneficio funcional (YAGNI).

**Alternativas consideradas**:
- *`yagmail`*: rechazada — envoltorio cómodo pero innecesario; dependencia nueva que viola el
  espíritu del Principio VII y añade superficie de auditoría sin resolver nada que `smtplib` no
  resuelva en ~15 líneas.
- *API de Gmail (REST) con OAuth*: rechazada — exige flujo OAuth2 interactivo y gestión de tokens
  de refresco, mucho más complejo que una contraseña de aplicación, y `docs/context.md` ya decidió
  SMTP.
- *Puerto 587 con `SMTP()` + `starttls()`*: funcionalmente equivalente; se elige 465/SSL implícito
  por ser el puerto documentado por Google para contraseñas de aplicación y evitar la negociación
  STARTTLS. Ambos quedan soportados por la configuración (host/puerto configurables, Decisión 3).

## Decisión 2: Módulo núcleo nuevo `banking.notify` con enganche en la capa CLI

**Decisión**: Crear `src/banking/notify.py` (componente núcleo, solo `logging`, sin `print()`) con
la clase `EmailNotifier`. El enganche con la ejecución vive en `cli/sync.py`: `handle()` invoca al
notificador en cada rama de terminación fallida, **antes** de devolver el exit code (FR-013),
inyectándolo como parámetro opcional (`notifier: EmailNotifier | None = None`) para los tests.

**Rationale**: La constitución (Principio V) exige que el email agregado se envíe "después de que
todos los conectores completen: si alguno falló" — dentro de la misma ejecución, no como paso
externo (decisión clarificada en la spec). La separación núcleo/CLI ya establecida (IT1-IT5) dicta
que la lógica de construcción del email y el envío SMTP vivan en un módulo núcleo testeable sin
captura de stdout, mientras que la decisión de *cuándo* notificar y *qué* exit code devolver es
política de terminación del comando — territorio de `cli/sync.py`, que ya posee la impresión del
resumen y los exit codes. La inyección opcional del notificador sigue el patrón de DI ya validado
(`writer`, `connectors`, `document_id`, `today` en `run_sync()`).

**Alternativas consideradas**:
- *Notificar dentro de `run_sync()`*: rechazada — mezclaría la política de notificación con la
  orquestación de obtención/escritura, obligaría a `run_sync()` a conocer la configuración SMTP, y
  complicaría los tests del pipeline (hoy puros: conectores + writer mockeados). Además, en fallo
  total `run_sync()` lanza `AllBanksFailedError`, y notificar dentro del bloque que lanza acoplaría
  el envío al mecanismo de excepciones.
- *Subcomando aparte `banking notify`*: rechazada — la decisión clarificada exige envío dentro del
  flujo de `banking sync` antes del exit code; un subcomando separado lo convertiría en un paso
  desacoplado que IT7 tendría que encadenar, con riesgo de perder el email si el encadenado falla.
- *Un paquete `banking/notify/` con submódulos*: rechazada — un solo fichero (~150 líneas) cubre
  config + construcción + envío; un paquete sería estructura sin contenido (Principio VII).

## Decisión 3: Claves de configuración en el SecretStore

**Decisión**: Cinco claves nuevas en el `.env` cifrado (SecretStore, IT1), leídas por
`_load_config()`:

| Clave | Obligatoria | Contenido |
|---|---|---|
| `SMTP_HOST` | Sí | `smtp.gmail.com` en producción (valor configurado, no hardcodeado) |
| `SMTP_PORT` | Sí | `465` en producción |
| `SMTP_USER` | Sí | Cuenta Gmail autenticada (también remitente) |
| `SMTP_PASSWORD` | Sí | Contraseña de aplicación Gmail (secreto, Principio IV) |
| `NOTIFY_EMAIL_TO` | Sí | Dirección de destino (el propietario) |

Si falta cualquiera de las cinco, o `SMTP_PORT` no es un entero válido, la configuración se
considera ausente → `DeliveryStatus.SKIPPED` con aviso en logs (FR-007), sin alterar el exit code.

**Rationale**: El Principio IV y el Anti-patrón #4 prohíben valores fijados en código; el
SecretStore es el mecanismo ya establecido (IT1) y en CI se mapea a GitHub Secrets (IT7). Las cinco
claves son obligatorias porque un email sin remitente, destino o credenciales no puede enviarse —
un valor por defecto parcial solo produciría envíos rotos a medias; es preferible el fallo explícito
y visible (aviso en logs) a un comportamiento ambiguo. El remitente es la propia cuenta autenticada
(suposición de la spec: no se soporta remitente distinto del autenticado — Gmail lo rechazaría por
política SPF/DMARC).

**Alternativas consideradas**:
- *Variables de entorno del SO directamente (`os.environ`)*: rechazada — rompe la uniformidad con
  `GOOGLE_SHEET_ID`/`GOOGLE_SHEETS_CREDENTIALS` (ya en SecretStore) y dejaría la contraseña sin
  cifrar en local (Principio IV).
- *Una sola clave `SMTP_CONFIG` con JSON*: rechazada — mezcla secretos y no-secretos en un blob,
  dificulta la rotación individual en GitHub Secrets (IT7) y no aporta nada sobre claves planas.
- *Claves opcionales con defaults en código (`smtp.gmail.com` hardcodeado)*: rechazada — Anti-patrón
  #4 (hardcoded configuration).

## Decisión 4: Señal de resultado de entrega — enum `DeliveryStatus` devuelto por `notify_failure()`

**Decisión**: `EmailNotifier.notify_failure(...)` devuelve `DeliveryStatus` (`enum.Enum`):
`SENT` (envío completado), `SKIPPED` (configuración ausente/incompleta — aviso en logs, FR-007) o
`FAILED` (envío intentado y fallido — error en logs, FR-006). `cli/sync.py` traduce `FAILED` a
exit code 4; `SKIPPED` y `SENT` no alteran el exit code del desenlace de sincronización. El
notificador nunca lanza excepciones hacia el CLI.

**Rationale**: FR-006 (decisión clarificada) exige distinguir "envío intentado y fallido" (exit 4)
de "no se intentó por falta de configuración" (exit code intacto, FR-007). Un enum devuelto es la
señal más simple que permite esa distinción sin excepciones de control de flujo y sin que el CLI
tenga que inspeccionar logs. El contrato "nunca lanza" concentra todo el manejo de errores SMTP en
el notificador y mantiene `handle()` por debajo del límite de complejidad 10 (Principio VI).

**Alternativas consideradas**:
- *`None` en éxito / excepción en fallo*: rechazada — obligaría al CLI a capturar excepciones del
  notificador, repartiendo la política de terminación entre dos módulos y arriesgando el
  enmascaramiento que FR-006 prohíbe.
- *`bool`*: rechazada — dos estados no pueden expresar tres resultados (falta SKIPPED vs FAILED).
- *Que el notificador devuelva el exit code directamente*: rechazada — invertiría la responsabilidad:
  la numeración de exit codes es contrato de la capa CLI (`contracts/cli-sync-interface.md`), no del
  núcleo.

## Decisión 5: Transporte SMTP inyectable vía fábrica

**Decisión**: `EmailNotifier.__init__(self, store: SecretStore | None = None, smtp_factory:
Callable[[EmailConfig], smtplib.SMTP] | None = None)`. En producción, la fábrica por defecto crea
`smtplib.SMTP_SSL(config.host, config.port, timeout=_SMTP_TIMEOUT_SECONDS)` y el notificador hace
`login` + `send_message` + `quit`. Los tests inyectan `Mock(spec=smtplib.SMTP)` (o una fábrica que
lo devuelva) — cero red real (Principio III, FR-010).

**Rationale**: Es el mismo patrón de DI ya validado en `SheetsWriter(client=...)` (IT3) y en
`run_sync(connectors=..., writer=...)` (IT4/IT5): un único punto de extensión que mockea toda la
interacción externa sin parchear internals del módulo (`monkeypatch.setattr("smtplib.SMTP_SSL", ...)`
es frágil y oculta la dependencia). La fábrica recibe la config ya resuelta, de modo que los tests
pueden verificar host/puerto sin tocar el SecretStore.

**Alternativas consideradas**:
- *Parchear `smtplib.SMTP_SSL` con `monkeypatch` en cada test*: rechazada — acopla los tests al
  nombre del símbolo interno, falla silenciosamente si la implementación cambia de `SMTP_SSL` a
  `SMTP`+STARTTLS, y no permite verificar la fábrica como unidad.
- *Clase `SmtpTransport` abstracta con subclase real y subclase fake*: rechazada — una interfaz de
  un solo método (`__call__(config) -> SMTP`) no justifica una jerarquía de clases; un `Callable`
  tipado es equivalente y más simple (Principio VII).
- *Inyectar la contraseña por parámetro en `notify_failure()`*: rechazada — el secreto debe fluir
  del SecretStore al punto de uso sin pasar por firmas públicas donde un log o un traceback podrían
  filtrarlo (Principio IV).

## Decisión 6: Excepciones del pipeline extendidas con contexto estructurado (retrocompatible)

**Decisión**: `AllBanksFailedError` y `SheetsSyncError` ganan atributos opcionales: `outcomes:
list[BankOutcome] | None = None` y `tab_name: str | None = None`. `run_sync()` los rellena al
lanzar; los mensajes `str(exc)` existentes no cambian. El notificador consume `outcomes` cuando está
disponible y hace fallback al parseo del mensaje solo si es `None` (compatibilidad con cualquier
invocador antiguo).

**Rationale**: FR-009 exige que la notificación consuma el resultado estructurado "sin reinterpretar
texto ni logs". En fallo total y en fallo de Sheets, `run_sync()` lanza en lugar de devolver el
`SyncSummary`, así que los motivos por banco y la pestaña destino solo están disponibles en la
excepción. Añadir atributos con valor por defecto `None` es retrocompatible: los tests existentes
de IT5 (`test_sync.py`, `test_cli_sync.py`) siguen pasando sin cambios, y el caso combinado
banco+escritura (decisión clarificada: un email con ambos) queda servido — `SheetsSyncError` lleva
los `outcomes` de la ejecución que sí obtuvo datos.

**Alternativas consideradas**:
- *Parsear el mensaje agregado de `AllBanksFailedError` ("Banco: motivo; ...")*: rechazada como
  mecanismo primario — es exactamente la reinterpretación de texto que FR-009 prohíbe; se mantiene
  solo como fallback defensivo.
- *Que `run_sync()` devuelva `SyncSummary` también en fallo total (sin lanzar)*: rechazada —
  rompería el contrato público de IT5 (`contracts/sync-pipeline-interface.md`) y el exit code 1 del
  CLI, con rework en tests y consumidores por una necesidad que los atributos opcionales resuelven.
- *Una excepción envolvente nueva `SyncFailureError` con todo el contexto*: rechazada — añade una
  capa de indirección nueva para un caso que dos atributos opcionales cubren (Principio VII).

## Decisión 7: Formato del email — texto plano en español, asunto clasificado

**Decisión**: `EmailMessage` con cabeceras `From` (cuenta autenticada), `To` (`NOTIFY_EMAIL_TO`) y
`Subject` en español que clasifica el fallo de un vistazo:

| Desenlace | Asunto |
|---|---|
| Fallo parcial | `Sincronización parcial: <k>/4 bancos — fallo en <YYYY-MM>` |
| Fallo total | `Sincronización fallida: los 4 bancos fallaron — <YYYY-MM>` |
| Fallo de Sheets (sin fallos de banco) | `Sincronización fallida: error escribiendo en Google Sheets — <YYYY-MM>` |
| Fallo combinado banco+escritura | `Sincronización fallida: error escribiendo en Google Sheets (con fallos de banco) — <YYYY-MM>` |

El cuerpo (texto plano, `Content-Type: text/plain; charset="utf-8"`) incluye: fecha de ejecución,
pestaña destino, duración, una línea por banco (`- <banco>: <n> movimientos` o
`- <banco>: FALLÓ — <motivo>`), y en fallo de Sheets la línea `ERROR (Sheets): <motivo>` como causa
principal. Ningún campo incluye credenciales ni secretos (FR-008); los motivos ya llegan
sanitizados desde los conectores (contrato IT5, FR-004).

**Rationale**: La decisión clarificada fija español (coherente con la salida del CLI de IT5, cuyos
literales — "Sincronización completada", "FALLÓ —" — se reutilizan para que email y consola sean
reconocibles entre sí). Texto plano porque el único destinatario es el propietario y la spec lo
asume explícitamente (Suposiciones); HTML añadiría plantillas sin valor. El asunto clasificado
cumple US1/US2 escenario 3 ("identificar de un vistazo el tipo de fallo sin abrir el cuerpo").

**Alternativas consideradas**:
- *Asunto en inglés / bilingüe*: rechazadas — la clarificación 2 de la spec fijó español.
- *HTML con tabla de bancos*: rechazada — la spec lo excluye (Suposiciones: "no se requiere HTML ni
  plantillas ricas").
- *Incluir el `SyncSummary` serializado en JSON adjunto*: rechazada — el destinatario es humano;
  el detalle por banco en texto ya cubre FR-005, y un adjunto invita a herramientas de parseo que
  no existen (YAGNI).

## Decisión 8: Alcance de pruebas automatizadas

**Decisión**: Tres ficheros de test, cada uno en el nivel donde vive su lógica:

- `tests/unit/test_notify.py` (nuevo): `EmailNotifier` aislado con `Mock(spec=smtplib.SMTP)` —
  contenido del email (asunto por desenlace, líneas por banco, motivo de Sheets, sin secretos),
  interacción SMTP (`SMTP_SSL` con host/puerto/timeout, `login`, `send_message`, `quit`),
  `DeliveryStatus` por escenario (SENT / SKIPPED por cada clave ausente / FAILED por cada error
  SMTP), y cierre del socket incluso cuando `send_message` lanza.
- `tests/unit/test_cli_sync.py` (ampliado): `handle()` con `run_sync` y `EmailNotifier` mockeados —
  exit codes 0/1/2/3 intactos con `SENT`/`SKIPPED`, exit 4 con `FAILED` (resumen impreso igualmente),
  notificador invocado exactamente una vez en cada rama fallida y **cero veces** en éxito completo,
  y el caso combinado banco+escritura (un email con ambos).
- `tests/unit/test_sync.py` (ampliado): las excepciones `AllBanksFailedError`/`SheetsSyncError`
  llevan `outcomes` y `tab_name` rellenos por `run_sync()` en los escenarios ya existentes.

**Rationale**: Cumple FR-011 (los seis escenarios obligatorios) y FR-010 (mock del transporte en
todas las pruebas) sin duplicar cobertura: el notificador se testea una vez aislado, el CLI se
testea con dobles de ambos colaboradores, y el pipeline solo verifica el nuevo contexto de sus
excepciones. Es el mismo reparto por niveles ya validado en IT5 (research.md Decisión 6 de IT5).

**Alternativas consideradas**:
- *Un test de integración que levante un SMTP local real (p. ej. `aiosmtpd` en localhost)*:
  rechazada — violaría el espíritu del Principio III (aunque sea localhost, es red real) y añadiría
  una dependencia de dev; `Mock(spec=smtplib.SMTP)` verifica la interacción con la misma eficacia.
- *Testear el contenido del email desde `test_cli_sync.py`*: rechazada — duplicaría la cobertura de
  `test_notify.py` y acoplaría los tests del CLI al formato del mensaje.
