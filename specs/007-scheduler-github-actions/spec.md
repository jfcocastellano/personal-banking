# Especificación de Funcionalidad: Scheduler en GitHub Actions (automatización completa)

**Rama de la funcionalidad**: `007-scheduler-github-actions`

**Creado**: 2026-10-17

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Configura el proceso de sincronización bancaria para que se ejecute
automáticamente cada día mediante GitHub Actions, y pueda dispararse también manualmente desde la interfaz de
GitHub. El workflow debe: ejecutarse una vez al día a una hora fija configurable; admitir disparo manual
mediante workflow_dispatch sin parámetros adicionales; usar GitHub Secrets para todas las credenciales (Enable
Banking session_id y configuración RSA, Google Sheets service account, Gmail SMTP), ninguna credencial en el
YAML del workflow; configurar timeout-minutes: 10 en el job; publicar un step summary con bancos procesados,
movimientos escritos, errores si los hay, duración total; ejecutar el mismo código que la ejecución local, sin
lógica específica de CI/CD en el código Python. El objetivo es que el sistema opere de forma completamente
autónoma sin ninguna acción diaria del propietario."

## Clarifications

Las decisiones de alcance no cubiertas explícitamente por la descripción del usuario se resuelven con los
valores ya ratificados en `docs/roadmap.md` (Iteración 7), `docs/context.md` (Constraints Duros: ejecución,
infraestructura y observabilidad), `specs/006-email-failure-notifications/spec.md` (exit codes `0`-`4` y
notificación por email) y la constitución del proyecto. Todas ellas están recogidas en la sección
[Suposiciones](#suposiciones); no queda ningún punto marcado como `[NEEDS CLARIFICATION]`.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Sincronización diaria automática sin intervención del propietario (Prioridad: P1)

Como propietario del proceso de sincronización financiera personal, necesito que el proceso se ejecute solo,
una vez al día, sin que yo haga nada, para que la pestaña del mes en curso refleje todos los movimientos de
mis cuatro bancos hasta el día de hoy sin que tenga que recordar lanzarlo ni tener un ordenador encendido.

**Por qué esta prioridad**: Es el objetivo final del proyecto (`docs/context.md`: el sistema se considera
completo cuando corre sin intervención humana todos los días). Sin esta historia, las iteraciones IT1-IT6
entregan un proceso que sólo funciona cuando alguien lo lanza a mano; con ella, el sistema pasa a estar
desplegado y operativo. Las otras dos historias son formas de operar y de observar esa misma ejecución
automática.

**Prueba independiente**: Se puede verificar de forma autónoma inspeccionando la definición del workflow
(existe un disparador programado diario y un único job que ejecuta el mismo comando que en local), y
comprobando el historial de ejecuciones de GitHub: al menos una ejecución iniciada por el disparador
programado, sin intervención humana, con resultado exitoso y con datos escritos en la hoja de cálculo.

**Escenarios de Aceptación**:

1. **Dado** el repositorio con el workflow desplegado en la rama principal, **Cuando** llega la hora diaria
   configurada, **Entonces** GitHub inicia el workflow sin ninguna acción del propietario y el proceso de
   sincronización se ejecuta hasta el final.
2. **Dado** que la ejecución automática termina con éxito completo, **Cuando** el propietario abre la hoja de
   cálculo, **Entonces** la pestaña del mes en curso contiene los movimientos del día y no ha recibido ningún
   email (coherente con IT6).
3. **Dado** que la ejecución automática termina con fallo parcial, total o de escritura, **Cuando** termina,
   **Entonces** GitHub marca la ejecución como fallida y el propietario recibe el email de aviso de IT6.

---

### Historia de Usuario 2 - Disparar la sincronización a mano desde GitHub (Prioridad: P2)

Como propietario, necesito poder lanzar la sincronización manualmente desde la interfaz de GitHub, sin
parámetros y sin tocar mi máquina, para recuperar una ejecución que no ha llegado a ocurrir o para verificar
un arreglo sin esperar al día siguiente.

**Por qué esta prioridad**: Es la válvula de escape operativa del sistema automático. No aporta la
automatización (eso es la Historia 1), pero evita que un fallo del scheduler deje al propietario sin forma de
recuperar el día; su ausencia obligaría a esperar 24 horas o a ejecutar en local con credenciales completas.

**Prueba independiente**: Se puede verificar de forma autónoma lanzando el workflow manualmente desde la
interfaz de GitHub con los campos por defecto (ninguno) y comprobando que produce el mismo resultado que una
ejecución programada: mismos pasos, mismo comando, mismos artefactos (pestaña escrita y, si procede, email).

**Escenarios de Aceptación**:

1. **Dado** el workflow desplegado, **Cuando** el propietario pulsa "Run workflow" sin rellenar ningún
   parámetro, **Entonces** la ejecución arranca y completa exactamente el mismo proceso que la programada.
2. **Dado** que el propietario lanza dos ejecuciones manuales seguidas, **Cuando** la segunda arranca antes de
   que la primera haya terminado, **Entonces** el sistema no permite que ambas escriban en la hoja de cálculo a
   la vez (una espera o se cancela), y ninguna deja la pestaña en un estado incoherente.

---

### Historia de Usuario 3 - Ver el resultado de cada ejecución en la propia página del workflow (Prioridad: P3)

Como propietario, necesito que cada ejecución publique un resumen legible en su página de GitHub, con los
bancos procesados, los movimientos escritos, los fallos y la duración total, para poder diagnosticar qué pasó
sin descargar los logs completos ni abrir un terminal.

**Por qué esta prioridad**: Mejora la operación, no la habilita. El email de IT6 ya avisa de los fallos y el
propio historial de ejecuciones indica si algo falló; el resumen ahorra tiempo al diagnosticar, sobre todo
cuando lo que falla es el arranque del proceso (caso que IT6 deja fuera de su alcance).

**Prueba independiente**: Se puede verificar de forma autónoma abriendo la página de una ejecución concreta y
comprobando que existe una sección de resumen con los cuatro datos (bancos, movimientos, fallos, duración),
tanto en una ejecución exitosa como en una fallida.

**Escenarios de Aceptación**:

1. **Dado** una ejecución con éxito completo, **Cuando** el propietario abre su página, **Entonces** el resumen
   muestra los cuatro bancos procesados, el total de movimientos escritos, "sin fallos" y la duración total.
2. **Dado** una ejecución con al menos un banco fallido, **Cuando** el propietario abre su página, **Entonces**
   el resumen lista los bancos fallidos con su motivo, además de los datos del escenario anterior.
3. **Dado** una ejecución que falla antes de producir un resultado de sincronización (por ejemplo, falta un
   secreto), **Cuando** el propietario abre su página, **Entonces** el resumen (o el paso fallido) indica
   explícitamente qué configuración falta, sin revelar su valor.

---

### Casos Límite

- ¿Qué ocurre si una sesión PSD2 de un banco ha caducado y nadie la ha re-autorizado? → La ejecución diaria
  falla de forma controlada (fallo parcial si los demás bancos responden), el workflow se marca como fallido y
  el propietario recibe el email de IT6 con el banco y el motivo. El sistema no intenta re-autorizar: la
  re-autorización es un flujo de navegador que requiere al propietario, y su procedimiento manual debe quedar
  documentado (ver FR-012).
- ¿Qué ocurre si falta un secreto o está mal formado? → La ejecución DEBE fallar en menos de un minuto con un
  mensaje que nombre la configuración ausente (sin revelar valores) y sin llegar a contactar con las APIs
  bancarias: el límite regulatorio PSD2 permite 4 peticiones de información de cuenta por día y cuenta, así
  que una ejecución mal configurada no debe consumir cuota.
- ¿Qué ocurre si el disparador programado se retrasa? → Se acepta un retardo de hasta ~15 minutos
  (`docs/context.md`, Constraints Duros); el proceso no asume una hora exacta ni depende de ella para calcular
  el rango de fechas (siempre sincroniza el mes en curso desde el día 1).
- ¿Qué ocurre si dos ejecuciones se solapan (programada + manual)? → El sistema NO DEBE permitir que dos
  ejecuciones escriban en la hoja de cálculo simultáneamente: la segunda espera o se cancela, de modo que la
  pestaña nunca queda a medio escribir por dos procesos a la vez.
- ¿Qué ocurre si la ejecución supera el tiempo máximo permitido? → El job se cancela al alcanzar el límite y
  NO se envía email (el proceso muere antes de notificar; el envío de IT6 ocurre dentro del proceso). El
  propietario lo detecta por el estado fallido de la ejecución y por el resumen parcial, y debe investigar los
  logs.
- ¿Qué ocurre si GitHub desactiva los workflows programados por inactividad del repositorio? → Riesgo conocido
  de la plataforma: los workflows programados se desactivan tras un periodo prolongado sin actividad en el
  repositorio. Se documenta como riesgo operativo y como comprobación periódica del propietario.
- ¿Qué ocurre si el propietario cambia la contraseña de aplicación de Gmail o rota las credenciales? → Basta
  con actualizar el secreto correspondiente en GitHub; no se requiere tocar el workflow ni el código.
- ¿Puede una ejecución revelar credenciales en logs o en el resumen? → No: ningún log, resumen ni mensaje DEBE
  incluir credenciales, tokens, JWT, identificadores de sesión completos ni el JSON de la cuenta de servicio,
  coherente con FR-008 de IT6 y FR-014 de IT5. Los secretos DEBEN enmascararse en los logs de la plataforma.

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE ejecutar la sincronización automáticamente una vez al día, a una hora fija
  configurable, sin ninguna acción del propietario.
- **FR-002**: El sistema DEBE permitir disparar la misma sincronización manualmente desde la interfaz de
  GitHub, sin parámetros de entrada adicionales.
- **FR-003**: Los dos caminos (programado y manual) DEBEN ejecutar exactamente el mismo programa que la
  ejecución local, sin lógica condicional específica de CI/CD en el código Python ni comandos alternativos en
  el workflow.
- **FR-004**: Todas las credenciales y parámetros sensibles (sesiones PSD2 por banco, `app_id` y clave RSA de
  Enable Banking, cuenta de servicio y documento de Google Sheets, credenciales SMTP y destinatario del
  email) DEBEN provenir de los secretos de GitHub; NINGUNA credencial puede aparecer en el fichero del
  workflow, en el repositorio ni en los logs.
- **FR-005**: El job DEBE tener un tiempo máximo de ejecución de 10 minutos.
- **FR-006**: Cada ejecución DEBE publicar, en su propia página de GitHub, un resumen legible con: bancos
  procesados (y cuáles fallaron con su motivo), movimientos escritos, fallos si los hay, y duración total.
- **FR-007**: El resultado de la ejecución DEBE reflejar fielmente el resultado de la sincronización: una
  ejecución cuyo proceso termina en fallo (exit code distinto de 0, incluido el fallo de entrega del email)
  DEBE quedar marcada como fallida; sólo el éxito completo queda como exitosa.
- **FR-008**: El sistema NO DEBE permitir dos ejecuciones simultáneas que escriban en la hoja de cálculo: el
  solapamiento entre una ejecución programada y una manual (o entre dos manuales) DEBE resolverse sin
  escrituras concurrentes.
- **FR-009**: Si falta o es inválido un parámetro sensible, la ejecución DEBE fallar de forma temprana (en
  menos de un minuto) con un mensaje que identifique la configuración ausente sin revelar su valor, y sin
  realizar peticiones a las APIs bancarias.
- **FR-010**: Ningún log, resumen de ejecución ni mensaje de error DEBE incluir credenciales, contraseñas,
  tokens, JWT, identificadores de sesión completos ni el JSON de la cuenta de servicio.
- **FR-011**: El workflow programado DEBE ser independiente del pipeline de integración continua: los pushes y
  pull requests NO DEBEN disparar la sincronización bancaria, y la integración continua DEBE seguir
  ejecutándose como hasta ahora en pushes a la rama principal y en pull requests.
- **FR-012**: El procedimiento manual de rotación de credenciales y de re-autorización de sesiones PSD2
  caducadas DEBE quedar documentado para el propietario, incluyendo los nombres de los secretos implicados.
- **FR-013**: La definición del workflow DEBE estar cubierta por pruebas automatizadas que no invoquen a
  GitHub ni realicen peticiones de red: al menos el disparador diario, el disparo manual sin parámetros, el
  límite de tiempo, la ausencia de credenciales literales y la ejecución del mismo comando que en local.
- **FR-014**: Antes de considerar la iteración cerrada DEBE existir constancia de al menos una ejecución real
  exitosa (iniciada por el disparador programado o manual) que haya escrito en la hoja de cálculo.

### Entidades Clave

- **Definición del workflow**: El documento que declara cuándo se ejecuta la sincronización (calendario diario
  y disparo manual), el tiempo máximo, los pasos y el resumen publicado; no contiene ningún valor sensible.
- **Ejecución (run)**: Un intento concreto del workflow, con su estado final (éxito/fallo), su duración y su
  resumen publicado; es la unidad que el propietario consulta para auditar el sistema.
- **Secreto de repositorio**: Cada valor sensible que el operador almacena en GitHub (sesiones PSD2, clave RSA,
  cuenta de servicio, documento, credenciales SMTP, destinatario) y que la ejecución materializa en el
  mecanismo de secretos del proyecto sin pasar por el repositorio ni por los logs.
- **Resultado de sincronización** *(existente, IT5)*: El agregado estructurado (estado global, desenlace por
  banco, pestaña, total de movimientos, duración) que el proceso ya produce y que alimenta tanto el resumen
  publicado como el email de IT6.
- **Resumen de ejecución**: La síntesis legible publicada en la página de la ejecución, derivada del resultado
  de sincronización (o del fallo temprano de configuración), sin contenido sensible.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Durante 7 días consecutivos, la sincronización se ejecuta automáticamente sin ninguna acción del
  propietario y cada ejecución termina con un estado registrado (éxito o fallo) en GitHub.
- **SC-002**: El 100% de las ejecuciones manuales probadas produce el mismo resultado que una ejecución
  programada equivalente (mismos pasos, mismo comando, mismo estado final para la misma situación de entrada).
- **SC-003**: El 100% de las ejecuciones probadas (exitosas y fallidas) publica un resumen con los cuatro datos
  requeridos: bancos procesados, movimientos escritos, fallos y duración total.
- **SC-004**: En el 100% de las ejecuciones con fallo de sincronización, la ejecución queda marcada como
  fallida y se dispara la notificación por email de IT6; en el 100% de las ejecuciones exitosas, no se envía
  ningún email.
- **SC-005**: Una búsqueda en el repositorio y en el workflow no encuentra ninguna credencial real
  (contraseñas, tokens, JWT, identificadores de sesión, JSON de cuenta de servicio), verificado de forma
  automatizada en integración continua.
- **SC-006**: El 100% de las ejecuciones completas termina por debajo del límite de 10 minutos, medido sobre el
  historial de ejecuciones reales.
- **SC-007**: Una ejecución con un parámetro sensible ausente falla en menos de 1 minuto, identifica la
  configuración que falta en el mensaje, y no realiza ninguna petición a las APIs bancarias.
- **SC-008**: En el 100% de los solapamientos probados, nunca hay dos ejecuciones escribiendo en la hoja de
  cálculo al mismo tiempo, y la pestaña queda en un estado coherente con una única ejecución.

## Suposiciones

- El despliegue se hace en GitHub Actions (free tier), con el repositorio alojado en GitHub y los secretos
  administrados por el propietario en la configuración del repositorio, según `docs/context.md`
  (Infraestructura). No se introduce ningún otro orquestador ni servidor propio.
- IT5 (pipeline multi-banco) e IT6 (notificación por email y exit codes `0`-`4`) están en la rama principal
  antes de desplegar esta iteración: el roadmap recomienda explícitamente desplegar IT7 con IT6 ya integrado,
  porque la única señal ante una sesión PSD2 caducada es el email.
- La hora diaria se expresa en la zona horaria de la plataforma (UTC) y el proceso no depende de ella: el
  rango sincronizado es siempre el mes en curso desde el día 1 hasta hoy, por lo que un retardo de minutos o
  una zona horaria distinta no cambian los datos escritos.
- El propietario es el único operador: no hay multiusuario, ni permisos por rol, ni notificación a terceros.
- La rotación de credenciales (contraseña de aplicación de Gmail, re-autorización PSD2, regeneración del JSON
  de cuenta de servicio) es un acto manual del propietario; esta iteración sólo documenta el procedimiento y
  asume que los secretos se actualizan en GitHub, no los automatiza.
- No se añaden reintentos automáticos ni ejecuciones de recuperación: un fallo diario se notifica (IT6) y se
  reintenta al día siguiente, o a mano mediante el disparo manual (Historia 2).
- El resumen publicado es texto plano derivado del resultado estructurado de la sincronización; no se generan
  artefactos adjuntos ni informes históricos.
- Los workflows programados de GitHub pueden desactivarse tras periodos prolongados sin actividad en el
  repositorio y pueden retrasarse ~15 minutos en horas de alta carga; ambos comportamientos se aceptan y se
  documentan como riesgos operativos.
- El sistema se considera cerrado con una única ejecución real exitosa documentada (roadmap, Iteración 7); no
  se exige un periodo de observación de producción más largo para dar la iteración por terminada.
