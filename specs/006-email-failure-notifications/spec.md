# Especificación de Funcionalidad: Notificación de Errores por Email

**Rama de la funcionalidad**: `006-email-failure-notifications`

**Creado**: 2026-10-16

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Implementa un mecanismo de notificación por email que informe al
propietario cuando el proceso de sincronización bancaria encuentra algún error. El comportamiento esperado:
- Fallo parcial (≥1 banco fallido): enviar un email con el resumen de fallos — qué bancos fallaron, el motivo
de cada fallo, y qué bancos se sincronizaron con éxito. - Fallo total (ningún banco responde o error de
configuración): enviar un email indicando el error general. - Éxito completo: no enviar ningún email. - Canal:
Gmail SMTP con contraseña de aplicación; la dirección de destino y las credenciales SMTP son configuración, no
código. - Fallo del propio envío: registrar en logs y no propagar una excepción que enmascare el error bancario
original. Todos los tests deben mockear el cliente SMTP. No se permiten envíos reales en CI. El objetivo es que
el propietario sea alertado de cualquier problema sin tener que acceder manualmente a los logs de GitHub
Actions."

## Clarifications

El alcance y las decisiones de diseño no cubiertas explícitamente por la descripción del usuario se resuelven,
salvo la excepción indicada abajo, con los valores por defecto documentados en la sección
[Suposiciones](#suposiciones), apoyados en `docs/roadmap.md` (Iteración 6), `docs/context.md` (sección
Notificaciones) y la constitución del proyecto (Principio V, "Partial Resilience"; SLO "Error email delivery
< 60 seconds"), todos ya ratificados como fuente de verdad del proyecto.

### Session 2026-10-16

- Q: ¿Qué debe hacer el sistema cuando la notificación por email no está configurada (falta la dirección de
  destino o las credenciales SMTP) y ocurre un fallo que debería notificarse? → A: Registrar el problema en
  logs como aviso y continuar — la ausencia de configuración de email nunca debe impedir que el proceso de
  sincronización complete su trabajo ni altere su resultado; la notificación es un añadido, no un requisito
  para operar.
- Q: ¿En qué idioma deben redactarse el asunto y el cuerpo del email de notificación? → A: Español —
  coherente con la salida del CLI ya existente; el único destinatario es el propietario.
- Q: ¿Debe el sistema hacer algo ante fallos repetidos día tras día (deduplicación o digestión de emails), o
  cada ejecución fallida notifica siempre de forma independiente? → A: Sin deduplicación ni memoria entre
  ejecuciones — cada ejecución fallida envía su email; no hay persistencia donde guardar fallos ya notificados
  (Principio VII) y el recordatorio diario ante un fallo persistente es el comportamiento deseado.
- Q: ¿La notificación debe formar parte del flujo del comando de sincronización (el email se envía dentro de
  la misma ejecución, antes de devolver el exit code), o ser un paso desacoplado que una futura orquestación
  invoque aparte? → A: Dentro del flujo del comando de sincronización — el email se envía antes de que el
  comando devuelva su exit code, según el Principio V de la constitución ("después de que todos los
  conectores completen: si alguno falló, enviar una única notificación de error agregada").
- Q: Si en la misma ejecución al menos un banco falla Y además la escritura en la hoja de cálculo también
  falla, ¿el email debe reportar ambas cosas o solo el fallo de escritura? → A: Un único email que reporte
  ambas cosas — el fallo de escritura como causa principal (nada se guardó) y, además, los bancos que
  fallaron con su motivo; el resultado estructurado ya contiene ambos datos en ese momento.
- Q: Cuando el envío del email falla pero la sincronización terminó en fallo parcial, ¿qué exit code debe
  devolver el comando? → A: Un exit code distinto (4) que señale el fallo de entrega de la notificación, en
  lugar del código que el desenlace de sincronización habría producido por sí solo; el resumen de la
  ejecución sigue imprimiéndose, de forma que el desenlace de sincronización siga siendo identificable.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Recibir un email cuando la sincronización falla parcialmente (Prioridad: P1)

Como propietario del proceso de sincronización financiera personal, cuando una ejecución termina con al menos
un banco fallido (y al menos otro sincronizado), necesito recibir en mi buzón de correo un email que me diga
qué bancos fallaron, por qué motivo falló cada uno, y qué bancos se sincronizaron con éxito, para enterarme
del problema y de su alcance sin tener que abrir los logs de GitHub Actions.

**Por qué esta prioridad**: Es el caso más frecuente y el que motiva la iteración — la resiliencia parcial de
IT5 hace que los fallos de un solo banco ya no aborten el proceso, así que sin email pasarían desapercibidos
(por ejemplo, una sesión PSD2 expirada de un banco dejaría de sincronizarse en silencio día tras día). Es la
historia central: las otras dos son variantes de la misma capacidad de notificar.

**Prueba independiente**: Se puede probar de forma completamente autónoma ejecutando el pipeline con los
conectores mockeados de forma que exactamente un banco falle y los otros tres devuelvan movimientos, con un
cliente de envío de email mockeado, y verificando que se envía exactamente un email cuyo contenido identifica
el banco fallido con su motivo y los tres bancos exitosos con sus recuentos.

**Escenarios de Aceptación**:

1. **Dado** que exactamente un banco de los cuatro falla y los otros tres se sincronizan correctamente,
   **Cuando** finaliza la ejecución, **Entonces** se envía exactamente un email a la dirección configurada
   cuyo contenido identifica el banco fallido, el motivo de su fallo, y los tres bancos sincronizados con su
   recuento de movimientos.
2. **Dado** que dos o más bancos fallan simultáneamente (por motivos distintos) y los restantes se
   sincronizan, **Cuando** finaliza la ejecución, **Entonces** el email identifica cada banco fallido con su
   propio motivo y los bancos exitosos con sus recuentos.
3. **Dado** que ocurre un fallo parcial, **Cuando** se envía el email, **Entonces** el asunto permite
   identificar de un vistazo que hubo un fallo parcial en la sincronización (sin necesidad de abrir el
   cuerpo).

---

### Historia de Usuario 2 - Recibir un email cuando la sincronización falla por completo (Prioridad: P2)

Como propietario, cuando una ejecución no sincroniza ningún banco (los cuatro conectores fallan) o el propio
paso de escritura en la hoja de cálculo falla, necesito recibir un email que indique el error general de la
ejecución, para saber que ese día no llegaron datos nuevos a mi hoja y diagnosticar si el problema es
generalizado.

**Por qué esta prioridad**: Es el caso más grave — sin datos de ningún banco, la hoja queda sin actualizar y
el propietario debe saberlo cuanto antes. Depende de que la capacidad de envío de la Historia 1 exista (mismo
canal, misma configuración); se separa porque el contenido y el disparador son distintos (error general frente
a resumen de fallos por banco).

**Prueba independiente**: Se puede probar de forma completamente autónoma ejecutando el pipeline con los
cuatro conectores mockeados para que fallen todos (o con el escritor de la hoja mockeado para que falle),
con un cliente de envío de email mockeado, y verificando que se envía exactamente un email que indica el
error general de la ejecución.

**Escenarios de Aceptación**:

1. **Dado** que los cuatro bancos fallan, **Cuando** finaliza la ejecución, **Entonces** se envía exactamente
   un email que indica el fallo total y el motivo de cada banco fallido.
2. **Dado** que al menos un banco se sincronizó pero la escritura en la hoja de cálculo falla, **Cuando**
   finaliza la ejecución, **Entonces** se envía exactamente un email que indica el fallo del paso de
   escritura (distinguiéndolo de un fallo de banco).
3. **Dado** que ocurre un fallo total, **Cuando** se envía el email, **Entonces** el asunto permite
   identificar de un vistazo que la sincronización falló por completo.

---

### Historia de Usuario 3 - No recibir emails cuando todo va bien (Prioridad: P3)

Como propietario, cuando una ejecución sincroniza los cuatro bancos y escribe en la hoja de cálculo sin
ningún error, necesito que no me llegue ningún email, para que cualquier email que reciba de este sistema
signifique siempre que hay un problema que atender (sin ruido ni fatiga de notificaciones).

**Por qué esta prioridad**: Es una garantía de comportamiento más que una funcionalidad — protege el valor de
las Historias 1 y 2 (que un email implique un problema). No tiene lógica propia: es la ausencia de envío en
el camino feliz.

**Prueba independiente**: Se puede probar de forma completamente autónoma ejecutando el pipeline con los
cuatro conectores mockeados devolviendo movimientos y el escritor funcionando, con un cliente de envío de
email mockeado, y verificando que no se realiza ninguna llamada de envío.

**Escenarios de Aceptación**:

1. **Dado** que los cuatro bancos se sincronizan correctamente y la escritura en la hoja de cálculo tiene
   éxito, **Cuando** finaliza la ejecución, **Entonces** no se envía ningún email.
2. **Dado** que un banco no tiene movimientos este mes (sincronización correcta con cero movimientos),
   **Cuando** finaliza la ejecución, **Entonces** no se envía ningún email (no es un fallo).

---

### Casos Límite

- ¿Qué ocurre si el envío del email falla (SMTP caído, credenciales rechazadas, sin red)? → El fallo del
  envío se registra en logs y no propaga una excepción no controlada; el comando devuelve el exit code 4
  (fallo de entrega de la notificación) en lugar del código del desenlace de sincronización, e imprime el
  resumen de la ejecución igualmente, de forma que el desenlace siga siendo identificable.
- ¿Qué ocurre si la notificación por email no está configurada (falta dirección de destino o credenciales
  SMTP) y ocurre un fallo notificable? → Se registra en logs como aviso y se continúa; la ausencia de
  configuración no impide que la sincronización complete su trabajo ni altera su resultado (ver
  [Clarifications](#clarifications)).
- ¿Qué ocurre si el proceso falla antes de llegar al paso de notificación (por ejemplo, un error de
  configuración al arrancar)? → Ese caso límite queda documentado como fuera de alcance de esta iteración
  (riesgo ya identificado en `docs/roadmap.md`, Iteración 6): la notificación se engancha a los resultados
  del pipeline de sincronización, no a errores de arranque del proceso.
- ¿Se envía un email por cada banco fallido o uno agregado? → Uno solo agregado por ejecución, con el detalle
  de todos los bancos fallidos y exitosos (Principio V de la constitución: "una única notificación de error
  agregada").
- ¿Qué ocurre si el mismo fallo se repite día tras día (por ejemplo, una sesión PSD2 expirada que nadie
  re-autoriza)? → Cada ejecución fallida envía su propio email, sin deduplicación ni memoria entre
  ejecuciones: no hay persistencia donde guardar fallos ya notificados (Principio VII), y el recordatorio
  diario ante un fallo persistente es el comportamiento deseado — no deja olvidar la re-autorización.
- ¿Qué ocurre si en la misma ejecución fallan bancos Y además falla la escritura en la hoja de cálculo? → Se
  envía un único email que reporta ambas cosas: el fallo de escritura como causa principal (nada se guardó)
  y los bancos fallidos con su motivo; el resultado estructurado de la ejecución ya contiene ambos datos.
- ¿Qué ocurre si la ejecución tiene éxito completo pero con cero movimientos en total (mes sin actividad en
  ningún banco)? → No se envía ningún email: es un éxito completo, no un fallo.
- ¿Qué ocurre si el asunto o el cuerpo del email contuvieran información sensible? → Ningún email DEBE
  incluir credenciales, tokens, JWT, identificadores de sesión completos ni el JSON de la cuenta de servicio
  de Google (mismo principio de seguridad ya aplicado a logs y resúmenes en IT5).

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE enviar exactamente un email de notificación por ejecución cuando el resultado
  de la sincronización es un fallo parcial (al menos un banco sincronizado y al menos uno fallido), con el
  detalle de qué bancos fallaron, el motivo de cada fallo, y qué bancos se sincronizaron con éxito con su
  recuento de movimientos.
- **FR-002**: El sistema DEBE enviar exactamente un email de notificación por ejecución cuando el resultado
  es un fallo total (ningún banco sincronizado) o un fallo del propio paso de escritura en la hoja de
  cálculo, indicando el error general de la ejecución y, cuando estén disponibles, los motivos por banco. Si
  en la misma ejecución concurren fallos de banco y fallo de la escritura, el email DEBE reportar ambos: el
  fallo de escritura como causa principal (nada se guardó) y los bancos fallidos con su motivo.
- **FR-003**: El sistema NO DEBE enviar ningún email cuando el resultado es un éxito completo (los cuatro
  bancos sincronizados, con independencia del número de movimientos, incluido cero).
- **FR-004**: El envío DEBE realizarse por Gmail SMTP autenticado con contraseña de aplicación; el remitente,
  la dirección de destino, y las credenciales SMTP DEBEN provenir de la configuración (mecanismos de secretos
  existentes del proyecto), nunca de valores fijados en el código.
- **FR-005**: El sistema DEBE construir el email con un asunto que permita identificar de un vistazo el tipo
  de fallo (parcial o total) y un cuerpo con el detalle: bancos fallidos con su motivo, bancos exitosos con
  su recuento, pestaña destino, y duración de la ejecución. El asunto y el cuerpo DEBEN redactarse en
  español, coherente con la salida del CLI ya existente.
- **FR-006**: Si el envío del email falla por cualquier motivo, el sistema DEBE registrar el fallo en logs y
  NO DEBE propagar una excepción no controlada que interrumpa el flujo de terminación del proceso. El comando
  DEBE devolver un exit code distinto (4) que señale el fallo de entrega de la notificación, en lugar del
  código que el desenlace de sincronización habría producido por sí solo; el resumen de la ejecución DEBE
  imprimirse igualmente, de forma que el desenlace de sincronización siga siendo identificable.
- **FR-007**: Si la configuración de notificación está incompleta o ausente cuando ocurre un fallo
  notificable, el sistema DEBE registrar la situación en logs como aviso y continuar sin enviar email, sin
  alterar el resultado de la sincronización ni su exit code (la ausencia de configuración no es un fallo de
  entrega: el email simplemente no se intenta).
- **FR-008**: Ningún email (asunto, cuerpo, cabeceras) DEBE incluir credenciales, contraseñas, tokens, JWT,
  identificadores de sesión completos, ni el JSON de la cuenta de servicio de Google.
- **FR-009**: El mecanismo de notificación DEBE consumir el resultado estructurado que el pipeline de
  sincronización ya produce (resumen con estado global y desenlace por banco), sin reinterpretar texto ni
  logs, y DEBE poder distinguir sin ambigüedad los tres resultados posibles (éxito completo, fallo parcial,
  fallo total) y el fallo del paso de escritura.
- **FR-010**: Todas las pruebas automatizadas DEBEN mockear el cliente de envío SMTP; ninguna prueba puede
  realizar un envío real, y el pipeline de CI DEBE hacer fallar cualquier prueba que lo intente.
- **FR-011**: El sistema DEBE contar, como mínimo, con pruebas automatizadas que cubran: (a) fallo parcial
  con un banco fallido → un email con el detalle correcto; (b) fallo total → un email con el error general;
  (c) fallo del paso de escritura → un email distinguiéndolo de un fallo de banco; (d) éxito completo →
  ningún email; (e) fallo del propio envío → registrado en logs, sin excepción no controlada y con exit code
  4; (f) configuración ausente → aviso en logs sin envío ni alteración del resultado ni del exit code.
- **FR-012**: La entrega del email de error DEBE completarse en menos de 60 segundos desde la detección del
  fallo, en línea con el SLO ya definido en la constitución del proyecto.
- **FR-013**: La notificación DEBE formar parte del flujo del comando de sincronización: el email DEBE
  enviarse dentro de la misma ejecución, antes de que el comando devuelva su exit code, de forma que el
  propietario reciba la alerta aunque el proceso termine inmediatamente después (Principio V de la
  constitución).

### Entidades Clave

- **Resultado de sincronización** *(existente, IT5)*: El agregado estructurado que el pipeline ya produce al
  terminar — estado global (éxito completo, fallo parcial, fallo total), desenlace por banco (éxito con
  recuento o fallo con motivo), pestaña escrita, total de movimientos y duración. Es la entrada del
  notificador; esta iteración no modifica su estructura.
- **Fallo del paso de escritura** *(existente, IT5)*: El caso especial en que los bancos respondieron pero la
  escritura en la hoja falló; el notificador debe tratarlo como fallo notificable con su propio mensaje,
  distinto del fallo de un banco.
- **Configuración de notificación**: El conjunto de valores que definen cómo y a quién se envía el email —
  servidor SMTP, puerto, remitente, destinatario y credenciales de aplicación — provisto por el operador a
  través de los mecanismos de configuración y secretos existentes, nunca incrustado en el código.
- **Email de notificación**: El mensaje único agregado por ejecución fallida, compuesto por un asunto que
  clasifica el tipo de fallo y un cuerpo con el detalle por banco; sin contenido sensible.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: En el 100% de las ejecuciones con fallo parcial probadas, se envía exactamente un email que
  identifica cada banco fallido con su motivo y cada banco exitoso con su recuento.
- **SC-002**: En el 100% de las ejecuciones con fallo total o fallo de escritura probadas, se envía exactamente
  un email que indica el error general, distinguiendo el fallo de escritura de un fallo de banco.
- **SC-003**: En el 100% de las ejecuciones exitosas probadas (incluido el caso de cero movimientos), no se
  envía ningún email.
- **SC-004**: En el 100% de los casos probados de fallo del envío, la ejecución termina sin excepción no
  controlada, el fallo queda registrado en logs, el resumen de la ejecución se imprime, y el comando devuelve
  el exit code 4 (fallo de entrega de la notificación).
- **SC-005**: La suite completa de pruebas automatizadas de la notificación se ejecuta con cero envíos SMTP
  reales, verificado en CI.
- **SC-006**: La entrega del email se completa en menos de 60 segundos desde la detección del fallo, en el
  100% de los envíos probados con el servidor SMTP mockeado respondiendo con normalidad.

## Suposiciones

- El canal de notificación es Gmail SMTP con contraseña de aplicación (requiere 2FA activo en la cuenta
  Google), usando la librería estándar de Python para SMTP, según `docs/context.md` (sección Notificaciones
  del stack técnico). La constitución ya lista Gmail SMTP entre los servicios externos que deben mockearse en
  tests (Principio III).
- Las credenciales SMTP (contraseña de aplicación) y la dirección de destino se provisionan mediante los
  mecanismos de secretos ya existentes del proyecto (SecretStore AES-256 en local; GitHub Secrets en CI) —
  esta iteración no crea un mecanismo de configuración nuevo, solo consume el existente.
- La notificación se engancha a los resultados del pipeline de sincronización (`banking sync`); los errores
  que impiden arrancar el proceso (por ejemplo, configuración corrupta al inicio) quedan fuera de alcance de
  esta iteración, riesgo ya documentado en `docs/roadmap.md` (Iteración 6).
- El formato del email es texto plano; no se requiere HTML ni plantillas ricas. Un asunto claro y un cuerpo
  de texto con el detalle por banco son suficientes para un único destinatario (el propietario).
- El envío es síncrono, dentro de la misma ejecución del proceso, antes de que termine; no se introduce
  encolamiento ni reintentos automáticos (YAGNI, Principio VII). Un envío fallido se registra y se pierde
  para esa ejecución.
- No hay deduplicación ni agrupación de emails entre ejecuciones: cada ejecución fallida notifica siempre de
  forma independiente. Un fallo persistente (por ejemplo, una sesión PSD2 expirada sin re-autorizar) genera
  un email por día — comportamiento intencionado, que actúa como recordatorio diario.
- Esta iteración no incluye el scheduler de GitHub Actions (IT7): la notificación se valida ejecutando el
  proceso localmente o en CI con mocks; el despliegue automatizado diario llega con IT7, que el roadmap
  recomienda desplegar con IT6 ya en `main`.
- El remitente del email es la misma cuenta Gmail que envía (autenticación SMTP); no se soporta remitente
  distinto del autenticado.
