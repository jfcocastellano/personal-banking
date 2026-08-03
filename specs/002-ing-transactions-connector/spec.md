# Especificación de Funcionalidad: Conector de Movimientos ING España (Enable Banking)

**Rama de la funcionalidad**: `002-ing-transactions-connector`

**Creado**: 2026-08-03

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Implementa un conector que se autentique con la API de Enable Banking
(agregador PSD2 europeo) y recupere los movimientos de una cuenta ING España para un rango de fechas.
El conector debe: autenticarse generando un JWT firmado con clave RSA privada (PS256 / RSA-PSS-SHA256)
leída de ~/.config/banca-personal/eb-config.json; leer el session_id PSD2 (válido 90-180 días) de los
secretos de configuración (no existen refresh tokens — si recibe HTTP 403 o detecta estado 'expired',
lanzar un error claro que indique que se requiere re-autorización manual); dado un rango de fechas,
paginar usando continuation_key hasta recuperar todos los registros; filtrar y devolver solo
transacciones con status BOOK (ignorar PDNG e INFO); normalizar el importe (CRDT = positivo, DBIT =
negativo, con divisa ISO 4217); respetar el límite PSD2 de 4 peticiones/cuenta/día y lanzar un error
descriptivo ante HTTP 429; no persistir datos (devolver la lista en memoria); emitir logs
estructurados (banco, inicio, número de registros, fin, estado). Todas las llamadas HTTP deben estar
mockeadas en los tests; no se permiten llamadas reales en CI. El objetivo es validar que Enable Banking
soporta ING España y que el proceso puede operar desatendido usando el session_id PSD2 almacenado
como secreto de configuración."

## Clarifications

### Session 2026-08-03

- Q: ¿Debe el spec exigir explícitamente que la clave privada RSA, el JWT firmado y el `session_id` completo nunca aparezcan en ningún log, incluidos mensajes de error o trazas de excepción? → A: Sí, requisito obligatorio — ninguno de estos datos debe aparecer nunca en ningún log, en ningún camino de ejecución.
- Q: ¿Qué fecha de la transacción se usa para el filtrado por rango, y es el `fin` del rango inclusivo? → A: Fecha de liquidación (`booking date`), rango inclusivo en inicio y fin.
- Q: ¿Qué se usa como identificador único de cada transacción para deduplicar entre páginas? → B: Construir una clave compuesta (fecha de liquidación + importe + descripción/contraparte) en lugar de asumir que la API entrega un identificador propio.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Recuperar movimientos liquidados en un rango de fechas (Prioridad: P1)

Como operador del proceso de sincronización financiera personal, necesito
recuperar todas las transacciones liquidadas (status `BOOK`) de mi cuenta ING
España en un rango de fechas dado, para que el paso posterior de reporting
(Google Sheets, IT3) disponga de datos precisos y completos, sin necesidad de
ninguna exportación manual desde la web del banco.

**Por qué esta prioridad**: Este es el valor central de la funcionalidad. Sin
ella, ING España no puede formar parte de la sincronización automatizada. El
resto de requisitos (paginación, filtrado, normalización) existen para que
este escenario sea correcto y completo.

**Prueba independiente**: Se puede probar de forma completamente autónoma
invocando el conector con una API de Enable Banking mockeada que devuelve un
conjunto de transacciones de prueba repartidas en varias páginas y estados, y
verificando que la lista devuelta contiene únicamente transacciones `BOOK`
con importes correctamente firmados y divisa indicada, dentro del rango de
fechas solicitado.

**Escenarios de Aceptación**:

1. **Dado** una sesión PSD2 válida y no expirada, y un rango de fechas cuyos
   resultados caben en una sola página de la API, **Cuando** el conector se
   ejecuta, **Entonces** devuelve todas las transacciones `BOOK` de ese rango
   con importes normalizados (CRDT positivo, DBIT negativo) y código de
   divisa ISO 4217, y emite un log de éxito con el nombre del banco, inicio y
   fin del rango, y número de registros.
2. **Dado** una sesión válida y un rango de fechas cuyos resultados abarcan
   varias páginas, **Cuando** el conector se ejecuta, **Entonces** sigue el
   `continuation_key` a través de todas las páginas y devuelve el conjunto de
   resultados combinado por completo.
3. **Dado** una página de respuesta con una mezcla de transacciones `BOOK`,
   `PDNG` e `INFO`, **Cuando** el conector procesa esa página, **Entonces**
   solo las transacciones `BOOK` aparecen en la lista devuelta.
4. **Dado** un rango de fechas que no arroja ninguna transacción, **Cuando**
   el conector se ejecuta, **Entonces** devuelve una lista vacía y registra un
   log de éxito con un número de registros igual a cero (esto no se
   considera un error).

---

### Historia de Usuario 2 - Detectar una sesión inutilizable y fallar con claridad (Prioridad: P2)

Como operador, cuando mi sesión PSD2 almacenada ha expirado o ha sido
revocada, necesito que el conector se detenga y me indique, en términos
claros, que debo re-autorizar manualmente a través del flujo de consentimiento
del banco en el navegador, para no quedarme sin saber por qué la
sincronización devolvió datos vacíos en silencio.

**Por qué esta prioridad**: Las sesiones PSD2 de Enable Banking no tienen
mecanismo de refresh token; la única recuperación posible es una
re-autorización manual y puntual en el navegador. Un conector que fallase en
silencio o con un error genérico ocultaría este problema hasta que el
operador notara datos ausentes días después.

**Prueba independiente**: Se puede probar de forma completamente autónoma
mockeando la API de Enable Banking para que devuelva HTTP 403, y por separado
para que devuelva un payload con estado de sesión `expired`, y verificando
que ambos casos lanzan un error distintivo y descriptivo que indica la
necesidad de re-autorización manual, sin devolver ningún dato parcial.

**Escenarios de Aceptación**:

1. **Dado** una sesión almacenada que la API rechaza con HTTP 403, **Cuando**
   el conector intenta recuperar transacciones, **Entonces** lanza un error
   cuyo mensaje indica explícitamente que se requiere re-autorización manual
   por navegador, y registra un log de fallo con el nombre del banco y el
   motivo.
2. **Dado** una sesión almacenada cuyo campo de estado indica `expired`,
   **Cuando** el conector se ejecuta, **Entonces** lanza el mismo tipo de
   error de re-autorización antes de intentar recuperar ninguna página de
   transacciones.
3. **Dado** que cualquiera de los fallos anteriores ocurre a mitad de la
   paginación (después de haber recuperado ya algunas páginas), **Cuando** se
   lanza el error, **Entonces** no se devuelve ninguna lista parcial de
   transacciones al llamador — la llamada falla en su conjunto.

---

### Historia de Usuario 3 - Respetar el límite de peticiones PSD2 e informar con claridad (Prioridad: P3)

Como operador, necesito que el conector reconozca cuándo se ha superado el
límite de peticiones PSD2 del banco (4 peticiones por cuenta y día), para que
el fallo se reporte como una condición conocida y esperada, en lugar de un
error de conector misterioso.

**Por qué esta prioridad**: Esta es una restricción real y documentada del
agregador que afecta directamente a la frecuencia con la que la
sincronización puede ejecutarse cada día con seguridad. Tiene menor
prioridad que la recuperación principal y el manejo de expiración de sesión
porque es un modo de fallo menos frecuente, pero aun así debe manejarse de
forma explícita en lugar de aparecer como un error HTTP genérico.

**Prueba independiente**: Se puede probar de forma completamente autónoma
mockeando la API de Enable Banking para que devuelva HTTP 429 en una
petición, y verificando que el conector lanza un error descriptivo de límite
de peticiones (no una excepción HTTP genérica) y registra el fallo con el
motivo.

**Escenarios de Aceptación**:

1. **Dado** que la API responde con HTTP 429 en la petición inicial,
   **Cuando** el conector se ejecuta, **Entonces** lanza un error descriptivo
   que indica que se ha superado el límite diario de peticiones PSD2, y
   registra un log de fallo con el nombre del banco y el motivo.
2. **Dado** que la API responde con HTTP 429 en una petición de paginación
   posterior (tras haber tenido éxito páginas anteriores), **Cuando** ocurre
   el error, **Entonces** el conector igualmente lanza el error de límite de
   peticiones y no devuelve un resultado parcial.

---

### Casos Límite

- ¿Qué ocurre cuando el fichero de configuración
  `~/.config/banca-personal/eb-config.json` no existe, no se puede leer, o le
  falta la clave privada RSA necesaria para firmar el JWT? → El conector DEBE
  fallar de inmediato con un error de configuración claro antes de intentar
  ninguna llamada de red.
- ¿Qué ocurre cuando el rango de fechas solicitado no es válido (fecha de fin
  anterior a la de inicio, o fechas en el futuro)? → El conector DEBE
  rechazar la solicitud con un error de validación claro antes de llamar a la
  API.
- ¿Qué ocurre cuando la API devuelve un error HTTP distinto de 403/429 (por
  ejemplo 500, 502)? → El conector DEBE lanzar un error descriptivo que
  identifique el banco y el estado inesperado, y registrar un log de fallo;
  NO DEBE reintentar en silencio ni devolver datos parciales.
- ¿Qué ocurre cuando a un registro de transacción le falta un campo esperado
  (importe, divisa, estado, indicador de crédito/débito)? → Según las reglas
  de validación de entrada del proyecto, el registro malformado DEBE
  omitirse con un log de advertencia, en lugar de hacer fallar toda la
  recuperación.
- ¿Qué ocurre si la paginación por `continuation_key` no termina (la API
  sigue devolviendo una clave indefinidamente)? → El conector DEBE aplicar un
  límite razonable al número de páginas recuperadas por llamada y fallar con
  un error descriptivo si se supera, en lugar de quedar en bucle infinito.
- ¿Qué ocurre si la misma transacción aparece en dos páginas consecutivas
  (solape en el límite de página)? → El conector DEBE deduplicar por la
  clave compuesta de fecha de liquidación, importe y
  descripción/contraparte antes de devolver los resultados.

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El conector DEBE autenticarse ante la API de Enable Banking
  generando un JWT firmado con el algoritmo PS256 (RSA-PSS-SHA256),
  utilizando la clave privada RSA presente en
  `~/.config/banca-personal/eb-config.json`.
- **FR-002**: El conector DEBE leer el `session_id` PSD2 almacenado para la
  cuenta ING España desde los secretos de configuración cifrados del
  proyecto (mediante el mecanismo SecretStore existente); NO DEBE solicitar
  ni ejecutar por sí mismo ningún flujo de autorización interactivo en el
  navegador.
- **FR-003**: El conector NO DEBE implementar ni depender de ningún flujo de
  refresh token; el `session_id` es la única credencial de acceso a los
  datos, de larga duración (90-180 días).
- **FR-004**: Cuando la API de Enable Banking responda con HTTP 403, o
  cuando el estado de sesión devuelto por la API indique `expired`, el
  conector DEBE lanzar un error distintivo cuyo mensaje indique claramente
  que se requiere re-autorización manual mediante el flujo de consentimiento
  del banco en el navegador. Este error DEBE lanzarse antes de devolver
  ningún dato de transacción al llamador.
- **FR-005**: Dadas una fecha de inicio y una fecha de fin, el conector DEBE
  recuperar todas las transacciones de ese rango siguiendo el mecanismo de
  paginación por `continuation_key` de la API hasta que no se devuelva
  ninguna clave adicional. El rango se evalúa sobre la **fecha de
  liquidación** (`booking date`) de cada transacción, y es **inclusivo** en
  ambos extremos: una transacción fechada exactamente en el día de inicio o
  en el día de fin DEBE incluirse en el resultado.
- **FR-006**: El conector DEBE incluir en su resultado únicamente las
  transacciones cuyo estado sea `BOOK`; las transacciones con estado `PDNG` o
  `INFO` DEBEN excluirse.
- **FR-007**: El conector DEBE normalizar el importe de cada transacción
  devuelta de forma que las transacciones de crédito (`CRDT`) se representen
  como un valor positivo y las de débito (`DBIT`) como un valor negativo, e
  incluir el código de divisa ISO 4217 junto al importe.
- **FR-008**: Cuando la API de Enable Banking responda con HTTP 429, el
  conector DEBE lanzar un error descriptivo que indique que se ha superado
  el límite diario de peticiones PSD2 (4 peticiones por cuenta y día),
  distinto del error de re-autorización de FR-004.
- **FR-009**: El conector NO DEBE persistir los datos de transacciones
  recuperados en ningún fichero, base de datos u otro almacenamiento; DEBE
  devolver el resultado como una lista en memoria a su llamador, únicamente
  durante la ejecución de una sola invocación.
- **FR-010**: El conector DEBE emitir un registro de log estructurado en
  cada invocación, que contenga: identificador del banco, fecha de inicio y
  fin del rango solicitado, y bien (a) en caso de éxito, el número de
  registros devueltos, o (b) en caso de fallo, el motivo del fallo.
- **FR-011**: El conector DEBE validar el rango de fechas solicitado (inicio
  anterior o igual a fin) antes de realizar ninguna llamada a la API, y
  rechazar los rangos inválidos con un error claro.
- **FR-012**: El conector DEBE omitir los registros de transacción a los que
  les falten campos obligatorios (importe, divisa, estado, indicador de
  crédito/débito), registrando una advertencia por cada registro omitido, en
  lugar de abortar toda la recuperación.
- **FR-013**: El conector DEBE deduplicar las transacciones cuando el mismo
  registro pudiera aparecer en varias respuestas paginadas, usando como
  clave de deduplicación la combinación de fecha de liquidación, importe y
  descripción/contraparte de la transacción (no se asume que la API
  proporcione un identificador propio de transacción).
- **FR-014**: Todas las pruebas automatizadas de este conector DEBEN
  mockear cada interacción HTTP con la API de Enable Banking; ninguna prueba
  puede realizar una llamada de red real, y el pipeline de CI DEBE hacer
  fallar cualquier prueba que lo intente.
- **FR-015**: El conector NO DEBE registrar en ningún log, bajo ninguna
  circunstancia (éxito, fallo, mensaje de excepción o traza), la clave
  privada RSA, el JWT firmado generado para la autenticación, ni el
  `session_id` completo; los logs de error DEBEN describir el motivo del
  fallo sin incluir estos valores ni fragmentos de ellos.

### Entidades Clave

- **Sesión PSD2**: La credencial de autorización de larga duración
  (90-180 días) para una única cuenta ING España, identificada por
  `session_id`. No tiene mecanismo de refresh; se invalida al expirar o ser
  revocada, momento en el cual solo una re-autorización manual y puntual por
  navegador puede restablecer el acceso.
- **Credencial de firma**: La clave privada RSA y la identidad de
  aplicación asociada, usadas para generar un JWT firmado con PS256 en cada
  autenticación ante la API, leídas del fichero de configuración local.
- **Transacción**: Un movimiento de cuenta liquidado (estado `BOOK`), con
  una clave de deduplicación compuesta por fecha de liquidación, importe y
  descripción/contraparte, un importe con signo (positivo para crédito,
  negativo para débito), un código de divisa ISO 4217 y una fecha de
  liquidación. Los estados no liquidados (`PDNG`, `INFO`) no se representan
  en la salida del conector.
- **Solicitud de rango de fechas**: La fecha de inicio y fin para las que
  se solicitan transacciones; delimita el alcance de una única invocación
  del conector.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Para cualquier rango de fechas que se mantenga dentro de la
  cuota diaria PSD2, el conector devuelve una lista completa de
  transacciones liquidadas (coincidente con un conjunto de referencia
  conocido) con un 100% de acierto en el signo del importe y el código de
  divisa, independientemente del número de páginas que abarquen los datos
  subyacentes.
- **SC-002**: Cuando la sesión almacenada no es válida (expirada o
  rechazada), el operador puede identificar, solo a partir del mensaje de
  error y sin leer código, que el siguiente paso necesario es una
  re-autorización manual por navegador.
- **SC-003**: Cuando se supera la cuota diaria de peticiones PSD2, el fallo
  se reporta como una condición distintiva y reconocible en el 100% de los
  casos, nunca como una excepción genérica o sin manejar.
- **SC-004**: Ningún registro de transacción se escribe jamás en disco, en
  una base de datos, ni en ningún almacenamiento persistente por parte de
  este conector, en ninguno de los escenarios de prueba.
- **SC-005**: El 100% de las invocaciones del conector (éxito o fallo)
  produce un registro de log estructurado suficiente para determinar, sin
  investigación adicional, qué banco se ejecutó, qué rango se solicitó y el
  resultado obtenido.
- **SC-006**: La suite completa de pruebas automatizadas de este conector se
  ejecuta con cero llamadas de red reales, verificado en CI.

## Suposiciones

- La sesión PSD2 (`session_id`) de la cuenta ING España ya ha sido
  establecida mediante un flujo de consentimiento manual por navegador,
  previo a esta funcionalidad; iniciar ese primer flujo de autorización
  queda fuera del alcance de este conector (que solo detecta cuándo se
  vuelve necesaria una re-autorización).
- `eb-config.json` y el secreto cifrado `session_id` ya contienen todo lo
  necesario para identificar la cuenta ING España concreta (identidad de la
  aplicación, clave RSA, referencia de cuenta/sesión); no está en alcance
  ningún paso adicional de descubrimiento de cuenta.
- Los valores de estado de transacción de la API de Enable Banking (`BOOK`,
  `PDNG`, `INFO`) y los indicadores de crédito/débito (`CRDT`, `DBIT`) siguen
  las convenciones ISO 20022 camt.05x y son estables entre peticiones.
- Operación local únicamente: este conector se invoca desde el mismo
  proceso programado descrito en la constitución del proyecto (propietario
  único, ejecución en GitHub Actions); no está en alcance ningún escenario
  multiusuario ni de invocación concurrente.
- Una única invocación del conector cubre una cuenta (ING España) y un
  rango de fechas contiguo; orquestar varios bancos o varios rangos es
  responsabilidad de un proceso llamador, no de esta funcionalidad.
- Un límite superior de páginas de paginación por invocación es una
  salvaguarda interna (según los Casos Límite) y no necesita ser
  configurable por el usuario en la v1.
