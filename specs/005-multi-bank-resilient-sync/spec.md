# Especificación de Funcionalidad: Sincronización Multi-Banco con Resiliencia Parcial

**Rama de la funcionalidad**: `005-multi-bank-resilient-sync`

**Creado**: 2026-08-13

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Extiende el pipeline de sincronización para soportar cuatro entidades
bancarias de forma resiliente: ING, Revolut, MyInvestor y Banco Sabadell, todas via Enable Banking como
agregador PSD2. El proceso debe: ejecutar el conector de cada banco de forma independiente y en secuencia;
si un conector falla (error de API, sesión expirada — HTTP 403 o estado 'expired' —, rate limit HTTP 429,
timeout u otro), registrar el error con su motivo y continuar con el siguiente banco sin abortar el proceso
completo; escribir en Google Sheets los movimientos de todos los bancos que respondieron correctamente en la
misma ejecución; producir al finalizar un resumen: qué bancos se sincronizaron (y cuántos movimientos), qué
bancos fallaron y por qué; si ningún banco responde, terminar con error sin propagar una excepción no
controlada. Escenarios de test obligatorios: todos ok, un banco falla y los otros tres continúan, todos los
bancos fallan. Todos los tests deben mockear las APIs externas. El objetivo es que el proceso sea resiliente
a indisponibilidades puntuales de una entidad bancaria sin perder los datos de las demás."

## Clarifications

El alcance y las decisiones de diseño no cubiertas explícitamente por la descripción del usuario se
resuelven, salvo la excepción indicada abajo, con los valores por defecto documentados en la sección
[Suposiciones](#suposiciones), apoyados en `docs/roadmap.md` (Iteración 5) y en la constitución del
proyecto (Principio V, "Partial Resilience"), ambos ya ratificados como fuente de verdad del proyecto.

### Session 2026-08-13

- Q: ¿Debe el orquestador imponer un techo de tiempo explícito por banco para proteger el presupuesto
  agregado de 2 minutos (SC-006), o cada conector se apoya únicamente en su propio comportamiento de
  timeout ya existente? → A: Sin techo explícito a nivel de pipeline — cada conector se apoya en su propio
  comportamiento de timeout ya existente, igual que el conector ING (IT2); no se introduce un mecanismo de
  vigilancia nuevo a nivel de orquestador.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Sincronizar los cuatro bancos en una sola ejecución (Prioridad: P1)

Como operador del proceso de sincronización financiera personal, necesito que una única ejecución del
comando obtenga y consolide los movimientos del mes en curso de mis cuatro entidades (ING, Revolut,
MyInvestor y Banco Sabadell) en la misma pestaña de mi hoja de cálculo, para tener una única fuente
consolidada de todos mis movimientos sin ejecutar el proceso banco por banco.

**Por qué esta prioridad**: Es la extensión directa del valor ya entregado para un solo banco (IT4) a los
cuatro bancos en scope del proyecto. Sin esto, la resiliencia parcial (Historia 2) no tiene sentido, porque
no habría más de un banco que sincronizar.

**Prueba independiente**: Se puede probar de forma completamente autónoma invocando el pipeline con los
cuatro conectores mockeados devolviendo movimientos conocidos, y verificando que la pestaña `YYYY-MM` del
mes en curso queda con los movimientos combinados de los cuatro bancos y que el resumen final reporta los
cuatro bancos como sincronizados con su recuento de movimientos correcto.

**Escenarios de Aceptación**:

1. **Dado** que los cuatro bancos tienen movimientos liquidados en lo que va del mes en curso, **Cuando** se
   ejecuta el comando de sincronización, **Entonces** la pestaña `YYYY-MM` del mes en curso queda con una
   fila de cabecera y una fila por cada movimiento de cada uno de los cuatro bancos, con el mismo esquema
   de columnas ya establecido (fecha de liquidación, nombre del banco, descripción, importe, divisa).
2. **Dado** que la ejecución se completa con los cuatro bancos sincronizados correctamente, **Cuando**
   finaliza, **Entonces** se muestra un resumen que indica, para cada uno de los cuatro bancos, que se
   sincronizó correctamente y cuántos movimientos aportó.
3. **Dado** que uno de los cuatro bancos no tiene ningún movimiento liquidado en lo que va del mes en
   curso, **Cuando** se ejecuta el comando, **Entonces** ese banco se considera sincronizado correctamente
   con cero movimientos (no es un fallo), y los movimientos de los otros bancos se escriben con normalidad.

---

### Historia de Usuario 2 - Continuar cuando un banco falla, sin perder los datos de los demás (Prioridad: P2)

Como operador, cuando uno de mis cuatro bancos no responde (sesión expirada, límite de peticiones agotado,
error de su API, tiempo de espera agotado, o cualquier otro fallo), necesito que el proceso siga
sincronizando y escribiendo en la hoja de cálculo los movimientos de los bancos que sí respondieron, para no
perder ni retrasar los datos de las entidades que funcionan correctamente por culpa de una indisponibilidad
puntual de una sola de ellas.

**Por qué esta prioridad**: Es el objetivo central de esta iteración — la razón de ser de "resiliencia
parcial" frente al comportamiento de todo-o-nada del pipeline de un solo banco (IT4). Depende de que la
Historia 1 ya funcione con los cuatro bancos en el camino feliz.

**Prueba independiente**: Se puede probar de forma completamente autónoma configurando uno de los cuatro
conectores mockeados para lanzar cada una de las categorías de fallo conocidas (sesión expirada, límite de
peticiones, error de API, timeout) mientras los otros tres devuelven movimientos conocidos, y verificando
que la pestaña queda con los movimientos de los tres bancos exitosos y que el resumen identifica el banco
fallido y el motivo, sin que el proceso se interrumpa ni propague una excepción.

**Escenarios de Aceptación**:

1. **Dado** que uno de los cuatro conectores lanza un error de sesión expirada (rechazo HTTP 403 o estado
   `expired` reportado por la API), **Cuando** se ejecuta el comando, **Entonces** el proceso continúa con
   los tres bancos restantes en secuencia, sin abortar la ejecución completa.
2. **Dado** que uno de los cuatro conectores lanza un error de límite de peticiones excedido (HTTP 429),
   **Cuando** se ejecuta el comando, **Entonces** el proceso continúa igual que en el escenario anterior.
3. **Dado** que uno de los cuatro conectores lanza un error de API inesperado, un tiempo de espera agotado,
   o cualquier otro fallo no contemplado explícitamente, **Cuando** se ejecuta el comando, **Entonces** el
   proceso lo trata como un fallo de ese banco (registrado con su motivo) y continúa igual que en los
   escenarios anteriores.
4. **Dado** que exactamente un banco de los cuatro falló y los otros tres se sincronizaron correctamente,
   **Cuando** finaliza la ejecución, **Entonces** la pestaña `YYYY-MM` queda con los movimientos de los tres
   bancos exitosos (y ninguno del banco fallido), y el resumen identifica cuáles tres bancos se
   sincronizaron (con su recuento de movimientos) y cuál banco falló y por qué motivo.
5. **Dado** que el banco que falló en esta ejecución sí se había sincronizado correctamente en una ejecución
   anterior ese mismo día, **Cuando** se ejecuta de nuevo y ese banco vuelve a fallar, **Entonces** la
   pestaña resultante refleja únicamente los bancos exitosos de la ejecución actual — no conserva los
   movimientos de ese banco de la ejecución anterior de forma silenciosa mezclados con el resto.

---

### Historia de Usuario 3 - Terminar de forma controlada cuando ningún banco responde (Prioridad: P3)

Como operador, si en un día concreto ninguno de mis cuatro bancos responde correctamente (por ejemplo, una
caída generalizada de Enable Banking), necesito que el proceso termine de forma clara y controlada — sin
colgarse, sin un volcado de excepción ilegible, y sin dejar la hoja de cálculo en un estado inconsistente —
para poder diagnosticar rápidamente que el problema es generalizado y no de un banco concreto.

**Por qué esta prioridad**: Es el caso límite del comportamiento de resiliencia — una capa de seguridad
operativa que evita que un fallo total termine en un cuelgue o en una excepción no controlada. Depende de
que las Historias 1 y 2 ya existan (es la variante ampliada de "cero bancos exitosos" que las Historias 1 y
2 no cubren).

**Prueba independiente**: Se puede probar de forma completamente autónoma configurando los cuatro
conectores mockeados para que fallen todos (con motivos distintos), y verificando que el proceso termina en
un estado de error identificable, sin lanzar una excepción no controlada al invocador, y sin haber intentado
escribir en Google Sheets.

**Escenarios de Aceptación**:

1. **Dado** que los cuatro conectores fallan (por cualquier combinación de motivos), **Cuando** se ejecuta
   el comando, **Entonces** el proceso NO intenta escribir en Google Sheets, termina en un estado de error
   identificable como fallo total, y no propaga ninguna excepción no controlada al invocador.
2. **Dado** que el fallo total ya ocurrió, **Cuando** finaliza la ejecución, **Entonces** se muestra un
   resumen que identifica los cuatro bancos como fallidos, con el motivo de cada uno.

---

### Casos Límite

- ¿Qué ocurre si un banco falla al obtener sus movimientos pero la escritura combinada en Google Sheets
  falla después, tras haber obtenido con éxito los movimientos de al menos otro banco? → Se trata como un
  fallo del propio paso de escritura en Sheets (no como un fallo adicional de banco), igual que en el
  pipeline de un solo banco (IT4); el resumen debe distinguir claramente un fallo de conector bancario de un
  fallo de la escritura en Sheets.
- ¿Qué ocurre si Enable Banking no soporta uno de los bancos (por ejemplo, si se confirma que MyInvestor no
  está disponible como agregado PSD2)? → Se trata como cualquier otro fallo de conector: registrado con su
  motivo, sin abortar el proceso ni bloquear la sincronización de los bancos restantes.
- ¿En qué orden se ejecutan los cuatro conectores? → Un orden fijo y reproducible (ING, Revolut, MyInvestor,
  Banco Sabadell), para que el resumen sea consistente entre ejecuciones.
- ¿Qué ocurre si dos o más bancos fallan simultáneamente por motivos distintos? → Cada fallo se registra de
  forma independiente con su propio motivo; el proceso continúa con cualquier banco restante en la
  secuencia y solo se considera fallo total si los cuatro fallan.
- ¿Qué ocurre si se alcanza el límite diario de peticiones PSD2 de Enable Banking (4 peticiones/cuenta/día)
  para uno de los bancos, pero no para los demás? → Ese banco concreto se registra como fallido por límite
  de peticiones excedido; los demás bancos, si no han alcanzado su propio límite, se sincronizan con
  normalidad.
- ¿Qué ocurre si el conector de un banco tarda en responder sin llegar a fallar explícitamente? → El
  pipeline no impone ningún techo de tiempo adicional a nivel de orquestador; se apoya en el comportamiento
  de timeout ya existente de cada conector (mismo patrón que el conector ING de IT2, ver
  [Clarifications](#clarifications)). Un banco especialmente lento puede consumir una parte
  desproporcionada del presupuesto de 2 minutos de SC-006, sin que el pipeline lo cancele de forma
  proactiva.

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE ejecutar el conector de cada uno de los cuatro bancos en scope (ING, Revolut,
  MyInvestor, Banco Sabadell) de forma independiente entre sí, en una secuencia fija y reproducible, dentro
  de una misma invocación del proceso de sincronización.
- **FR-002**: El sistema DEBE continuar ejecutando el conector del siguiente banco en la secuencia aunque el
  conector de un banco anterior falle; ningún fallo de un conector individual DEBE interrumpir la ejecución
  de los conectores restantes.
- **FR-003**: Cuando el conector de un banco falla, el sistema DEBE registrar el fallo asociado a ese banco
  junto con un motivo identificable, cubriendo como mínimo las siguientes categorías: sesión expirada o
  rechazada (incluye rechazo HTTP 403 y estado `expired` reportado por la API), límite de peticiones
  excedido (HTTP 429), error inesperado de la API bancaria, tiempo de espera agotado, y cualquier otro
  fallo no contemplado explícitamente en las categorías anteriores.
- **FR-004**: El registro de un fallo de conector NO DEBE incluir credenciales, tokens, JWT, ni
  identificadores de sesión completos del banco correspondiente.
- **FR-005**: El sistema DEBE combinar los movimientos transformados de todos los bancos cuyo conector
  respondió correctamente en la ejecución actual, y escribirlos en la pestaña de Google Sheets del mes en
  curso, siguiendo el mismo esquema de columnas ya establecido (fecha de liquidación, nombre del banco,
  descripción, importe, divisa).
- **FR-006**: El sistema NO DEBE incluir en la escritura a Google Sheets ningún movimiento de un banco cuyo
  conector haya fallado en la ejecución actual, incluso si ese banco se había sincronizado correctamente en
  una ejecución anterior del mismo día.
- **FR-007**: Si al menos un banco se sincroniza correctamente, el sistema DEBE completar la escritura en
  Google Sheets con los datos disponibles de los bancos exitosos, independientemente de que uno o más de
  los otros bancos hayan fallado.
- **FR-008**: Si ninguno de los cuatro bancos se sincroniza correctamente, el sistema NO DEBE intentar
  escribir en Google Sheets, DEBE terminar en un estado de error identificable como fallo total, y NO DEBE
  propagar una excepción no controlada al invocador.
- **FR-009**: Al finalizar la ejecución (con éxito completo, fallo parcial o fallo total), el sistema DEBE
  producir un resumen que indique, para cada uno de los cuatro bancos: si se sincronizó correctamente y
  cuántos movimientos aportó, o si falló y cuál fue el motivo.
- **FR-010**: El resumen final DEBE permitir distinguir sin ambigüedad entre los tres resultados posibles de
  una ejecución — éxito completo (los cuatro bancos sincronizados), fallo parcial (al menos uno
  sincronizado y al menos uno fallido), y fallo total (los cuatro fallidos) — de forma que un proceso
  externo (por ejemplo, un notificador futuro) pueda reaccionar de forma distinta a cada uno sin tener que
  interpretar el texto del resumen.
- **FR-011**: Los conectores de Revolut, MyInvestor y Banco Sabadell DEBEN seguir el mismo contrato ya
  validado por el conector ING existente: obtención de movimientos liquidados para un rango de fechas,
  exposición pública del nombre del banco, y el mismo conjunto de categorías de error (configuración
  inválida, sesión expirada o rechazada, límite de peticiones excedido, error de API, rango de fechas
  inválido).
- **FR-012**: Todas las pruebas automatizadas de este pipeline DEBEN mockear los cuatro conectores bancarios
  y el escritor de Google Sheets; ninguna prueba puede realizar una llamada de red real a Enable Banking ni
  a Google Sheets, y el pipeline de CI DEBE hacer fallar cualquier prueba que lo intente.
- **FR-013**: El sistema DEBE contar, como mínimo, con pruebas automatizadas que cubran los tres escenarios
  siguientes: (a) los cuatro bancos responden correctamente, (b) exactamente un banco falla y los otros
  tres se sincronizan y se escriben correctamente, (c) los cuatro bancos fallan y el proceso termina en un
  estado de error controlado sin escribir en Google Sheets.
- **FR-014**: Ningún mensaje producido por el sistema (resumen, log, error) DEBE incluir credenciales, JWT,
  identificadores de sesión completos, ni el JSON de la cuenta de servicio de Google, para ninguno de los
  cuatro bancos.

### Entidades Clave

- **Resultado de sincronización por banco**: El desenlace de ejecutar el conector de un banco concreto en
  una ejecución — o bien un éxito con el número de movimientos obtenidos, o bien un fallo con el motivo
  categorizado (sesión expirada, límite de peticiones, error de API, timeout, u otro).
- **Resumen de ejecución**: El agregado de los cuatro resultados de sincronización por banco de una misma
  ejecución, junto con el estado global resultante (éxito completo, fallo parcial, o fallo total) y el
  número total de movimientos escritos en Google Sheets.
- **Conector bancario**: La abstracción común a los cuatro bancos que obtiene los movimientos liquidados de
  una cuenta para un rango de fechas dado, vía Enable Banking como agregador PSD2; ya existente para ING
  (IT2), y a construir en esta iteración para Revolut, MyInvestor y Banco Sabadell siguiendo el mismo
  contrato.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Con los cuatro bancos respondiendo correctamente, una única ejecución deja la pestaña del mes
  en curso con los movimientos combinados de los cuatro bancos, y el resumen confirma los cuatro como
  sincronizados con su recuento de movimientos correcto, en el 100% de los casos probados.
- **SC-002**: Cuando exactamente un banco falla (por cualquiera de las categorías de fallo conocidas), la
  ejecución completa sin abortar: los otros tres bancos quedan reflejados en la pestaña y el resumen
  identifica el banco fallido y su motivo, en el 100% de los casos probados.
- **SC-003**: Cuando los cuatro bancos fallan, el proceso termina en un estado de error identificable sin
  lanzar una excepción no controlada, y la pestaña de Google Sheets no se modifica, en el 100% de los casos
  probados.
- **SC-004**: El 100% de las ejecuciones (éxito completo, fallo parcial o fallo total) produce un resumen
  suficiente para determinar, sin inspeccionar logs ni código, qué bancos se sincronizaron, cuántos
  movimientos aportó cada uno, y qué bancos fallaron y por qué.
- **SC-005**: La suite completa de pruebas automatizadas del pipeline multi-banco se ejecuta con cero
  llamadas de red reales a Enable Banking o a Google Sheets, verificado en CI.
- **SC-006**: Una ejecución completa de los cuatro bancos (obtención de movimientos de los cuatro conectores
  y escritura combinada en Sheets) se completa en menos de 2 minutos, en línea con el SLO de sincronización
  completa (los cuatro bancos) ya definido en la constitución del proyecto.

## Suposiciones

- Los conectores de Revolut, MyInvestor y Banco Sabadell se construyen dentro de esta misma iteración,
  replicando el contrato ya validado por el conector ING (IT2) — misma interfaz de obtención de
  movimientos, mismo esquema de datos normalizado, y el mismo conjunto de categorías de error — según la
  Definición de Hecho documentada en `docs/roadmap.md` (Iteración 5).
- Cada uno de los cuatro bancos requiere su propio `session_id` PSD2 (y, si aplica, su propio fichero de
  configuración de credenciales de aplicación), ya autorizados y provistos por el operador antes de la
  ejecución. Esta funcionalidad no gestiona el flujo de autorización inicial (consentimiento vía navegador)
  de ningún banco — solo consume sesiones ya autorizadas, igual que el conector ING existente.
- Si se confirma que Enable Banking no soporta alguno de los bancos en scope (riesgo documentado para
  MyInvestor en `docs/context.md`), esta iteración se entrega igualmente con los bancos sí soportados; el
  banco no soportado se trata como cualquier otro fallo de conector (categorizado, registrado, sin abortar
  el proceso) hasta que se resuelva en un trabajo de investigación aparte.
- El envío de notificaciones por email ante fallos (parciales o totales) queda fuera del alcance de esta
  iteración — está planificado como una iteración posterior (IT6) según `docs/roadmap.md`. El resumen de
  esta iteración se expone como resultado estructurado del proceso, listo para que una iteración futura lo
  consuma y lo envíe por email.
- El orden de ejecución de los cuatro conectores es fijo: ING, Revolut, MyInvestor, Banco Sabadell — el
  mismo orden en que la constitución del proyecto los enumera (Principio V).
- Esta iteración reutiliza la pestaña única por mes (`YYYY-MM`) ya establecida por el escritor de Google
  Sheets (IT3) y el pipeline de un solo banco (IT4); no se introduce una pestaña por banco ni ningún otro
  esquema de particionado nuevo.
- El ID del documento de Google Sheets destino y las credenciales de la cuenta de servicio ya están
  configurados mediante los mecanismos existentes (IT1, IT3); esta funcionalidad no gestiona su obtención
  inicial.
- El pipeline no introduce un mecanismo de timeout nuevo a nivel de orquestador (decidido en
  [Clarifications](#clarifications)); reutiliza el comportamiento de timeout ya establecido por el cliente
  HTTP de cada conector, igual que el conector ING (IT2), sin imponer un techo de tiempo adicional por
  banco.
