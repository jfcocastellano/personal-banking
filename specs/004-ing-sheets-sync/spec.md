# Especificación de Funcionalidad: Pipeline de Sincronización ING → Google Sheets

**Rama de la funcionalidad**: `004-ing-sheets-sync`

**Creado**: 2026-08-09

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Implementa el proceso principal de sincronización que conecta el
conector de Enable Banking (ING) con el writer de Google Sheets. El proceso debe: ser invocable desde
línea de comandos como punto de entrada principal del sistema (`python -m banking sync`); obtener los
movimientos del mes en curso de la cuenta ING desde el día 1 del mes hasta la fecha de ejecución;
transformar cada movimiento al esquema tabular (columnas mínimas: fecha de valor, nombre del banco,
descripción, importe, divisa); escribir en la pestaña YYYY-MM del mes en curso, de forma idempotente si
se ejecuta varias veces el mismo día (sobreescritura sin duplicados); emitir un resumen al finalizar
(banco, movimientos escritos, pestaña destino, duración total). Todos los sistemas externos (Enable
Banking API y Google Sheets API) deben estar mockeados en los tests; no se permiten llamadas reales en
CI. El objetivo es un sistema funcional demostrable para un banco, que sirva como base verificable para
añadir más entidades."

## Clarifications

### Session 2026-08-09

- Q: El conector ING (IT2) solo expone la fecha de liquidación (`booking_date`); la petición original pide una columna "fecha de valor". ¿Qué fecha debe usarse en esa columna? → A: Reutilizar `booking_date` (fecha de liquidación) ya disponible, y renombrar la columna a "fecha de liquidación" en vez de "fecha de valor" — sin extender el conector de IT2 en esta iteración.
- Q: ¿Debe el pipeline usar un único código de salida no-cero para cualquier fallo, o distinguir por sistema responsable? → A: Dos códigos de salida distintos por sistema responsable — `1` cuando falla la obtención de movimientos de ING, `2` cuando falla la escritura en Google Sheets — para que un futuro scheduler o notificador pueda reaccionar sin parsear el mensaje.
- Q: ¿De dónde obtiene el pipeline el nombre del banco usado en la columna y en el resumen — un literal propio, una constante pública del conector, o configuración externa? → A: El conector ING (IT2) expone el nombre del banco como constante/propiedad pública, y el pipeline la reutiliza; evita duplicar el literal ya definido internamente en `ing.py`.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Ejecutar la sincronización con un solo comando (Prioridad: P1)

Como operador del proceso de sincronización financiera personal, necesito
ejecutar un único comando que obtenga los movimientos de mi cuenta ING del
mes en curso y los deje escritos en la pestaña correspondiente de mi hoja
de cálculo, para no tener que exportar ni pegar datos manualmente.

**Por qué esta prioridad**: Es el valor central de la funcionalidad — el
primer resultado completamente demostrable del sistema. Sin esto, el
conector (IT2) y el escritor (IT3) siguen siendo piezas aisladas sin un
proceso que las conecte.

**Prueba independiente**: Se puede probar de forma completamente autónoma
invocando el comando con el conector ING y el escritor de Sheets mockeados,
devolviendo un conjunto de movimientos conocido, y verificando que la
pestaña `YYYY-MM` del mes en curso queda con esos movimientos transformados
y que el resumen final reporta el banco y el número de movimientos
correctos.

**Escenarios de Aceptación**:

1. **Dado** que la cuenta ING tiene movimientos liquidados en lo que va del
   mes en curso, **Cuando** se ejecuta `python -m banking sync`,
   **Entonces** la pestaña `YYYY-MM` del mes en curso queda con una fila de
   cabecera y una fila por cada movimiento, con las columnas en el orden
   fijo del esquema: fecha de liquidación, nombre del banco, descripción,
   importe, divisa (FR-003).
2. **Dado** que la cuenta no tiene ningún movimiento liquidado en lo que va
   del mes en curso, **Cuando** se ejecuta el comando, **Entonces** la
   pestaña queda solo con la fila de cabecera y el resumen indica cero
   movimientos escritos, sin considerarse un error.
3. **Dado** que la ejecución se completa con éxito, **Cuando** finaliza,
   **Entonces** se muestra un resumen con el nombre del banco, el número
   de movimientos escritos, el nombre de la pestaña destino y la duración
   total de la ejecución.

---

### Historia de Usuario 2 - Ejecutar varias veces el mismo día sin duplicar (Prioridad: P2)

Como operador, necesito poder volver a ejecutar la sincronización varias
veces el mismo día (por ejemplo, para refrescar los datos tras una nueva
transacción, o tras corregir un problema previo) sin que la pestaña
acumule movimientos duplicados, para poder confiar en el resultado sin
tener que revisar manualmente si hay repeticiones.

**Por qué esta prioridad**: Depende de que la escritura básica (Historia 1)
ya funcione; es una garantía de calidad sobre esa escritura, no una
capacidad independiente nueva.

**Prueba independiente**: Se puede probar de forma completamente autónoma
ejecutando el pipeline dos veces seguidas con el mismo conjunto de
movimientos mockeado, y verificando que la pestaña resultante es idéntica
tras ambas ejecuciones (mismo número de filas, sin duplicados).

**Escenarios de Aceptación**:

1. **Dado** que el pipeline ya se ejecutó con éxito hoy para el mes en
   curso, **Cuando** se vuelve a ejecutar el mismo día con el mismo rango
   de movimientos subyacente, **Entonces** la pestaña resultante contiene
   exactamente el mismo conjunto de filas que tras la primera ejecución,
   sin duplicados.
2. **Dado** que entre dos ejecuciones del mismo día aparece un movimiento
   nuevo (por ejemplo, una transacción registrada más tarde ese día),
   **Cuando** se ejecuta de nuevo, **Entonces** la pestaña queda con el
   conjunto actualizado completo (incluyendo el nuevo movimiento), sin
   conservar ninguna fila de la ejecución anterior que ya no corresponda
   al estado actual de los movimientos del mes.

---

### Historia de Usuario 3 - Diagnosticar un fallo sin inspeccionar código (Prioridad: P3)

Como operador, cuando la sincronización falla (por ejemplo, porque la
sesión de ING ha expirado o el documento de Sheets no es accesible),
necesito un mensaje claro que me diga qué ha fallado, para saber si tengo
que re-autorizar el banco, revisar permisos del documento, o esperar a que
se restablezca un límite de cuota, sin tener que leer el código ni
depurar en vivo.

**Por qué esta prioridad**: Es una capa transversal de calidad que traduce
los fallos ya conocidos del conector (IT2) y del escritor (IT3) a algo
legible al nivel del pipeline completo; depende de que ambas piezas ya
existan.

**Prueba independiente**: Se puede probar de forma completamente autónoma
forzando por separado un fallo del conector ING mockeado y un fallo del
escritor de Sheets mockeado, y confirmando que en ambos casos el comando
termina con un código de salida distinto de cero y un mensaje que
identifica cuál de los dos sistemas falló y por qué.

**Escenarios de Aceptación**:

1. **Dado** que el conector ING lanza cualquiera de sus errores conocidos
   (re-autorización requerida, límite de cuota, error de API, error de
   configuración), **Cuando** se ejecuta el comando, **Entonces** el
   pipeline NO intenta escribir en Google Sheets, muestra un mensaje que
   identifica el fallo como proveniente de la obtención de movimientos de
   ING, y termina con el código de salida `1`.
2. **Dado** que el conector ING obtiene los movimientos con éxito pero el
   escritor de Sheets falla (documento inaccesible, cuota excedida, error
   de API, configuración inválida), **Cuando** ocurre el fallo,
   **Entonces** el pipeline muestra un mensaje que identifica el fallo
   como proveniente de la escritura en Google Sheets, y termina con el
   código de salida `2`.

---

### Casos Límite

- ¿Qué ocurre si la pestaña `YYYY-MM` del mes en curso todavía no existe
  (por ejemplo, el primer día de un mes nuevo)? → El pipeline DEBE dejar
  que se cree automáticamente (comportamiento ya soportado por el escritor
  de Sheets, IT3), sin ningún paso manual adicional.
- ¿Qué ocurre si se ejecuta el mismo día en el que ya se alcanzó el límite
  diario de peticiones PSD2 de Enable Banking (4 peticiones/cuenta/día)? →
  El pipeline DEBE reportar el fallo de cuota de forma clara (Historia 3),
  sin intentar escribir en Sheets, igual que cualquier otro fallo del
  conector.
- ¿Qué ocurre si el rango de fechas solicitado es un único día (se ejecuta
  el día 1 del mes)? → Es un rango válido de un solo día; el pipeline lo
  procesa con normalidad, sin tratamiento especial.
- ¿Qué ocurre si el proceso se interrumpe (p. ej. se mata el proceso) justo
  después de que la escritura en Sheets haya empezado pero antes de
  completarse? → Fuera del control de este pipeline: el comportamiento en
  ese caso es el que ya documenta el escritor de Sheets (IT3) ante un
  fallo a mitad de operación — no hay garantía transaccional adicional
  introducida por este pipeline.

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE exponer un punto de entrada de línea de
  comandos (`python -m banking sync`) que ejecute el pipeline completo sin
  requerir argumentos adicionales.
- **FR-002**: El pipeline DEBE obtener del conector ING España todos los
  movimientos liquidados desde el día 1 del mes en curso (según la fecha
  de ejecución) hasta la fecha de ejecución, ambos extremos inclusive.
- **FR-003**: El pipeline DEBE transformar cada movimiento obtenido a una
  fila tabular con, como mínimo, las siguientes columnas en este orden
  fijo: fecha de liquidación (reutilizando `booking_date`, ya expuesto por
  el conector ING de IT2 — no una fecha de valor PSD2 distinta; ver
  Clarifications), nombre del banco, descripción, importe, divisa.
- **FR-004**: El pipeline DEBE escribir la fila de cabecera y las filas
  transformadas en la pestaña del documento de Google Sheets configurado,
  cuyo nombre coincide con el mes en curso en formato `YYYY-MM`.
- **FR-005**: El pipeline DEBE producir el mismo contenido final en la
  pestaña del mes en curso independientemente de cuántas veces se ejecute
  en el mismo día para el mismo conjunto de movimientos subyacente
  (idempotencia por sobrescritura completa, sin filas duplicadas).
- **FR-006**: Al finalizar con éxito, el pipeline DEBE mostrar un resumen
  que incluya: nombre del banco, número de movimientos escritos, nombre de
  la pestaña destino, y duración total de la ejecución.
- **FR-007**: Si la obtención de movimientos del conector ING falla por
  cualquier motivo, el pipeline NO DEBE intentar escribir en Google
  Sheets, DEBE mostrar un mensaje que identifique el fallo como
  proveniente de ING, y DEBE terminar con el código de salida `1`.
- **FR-008**: Si la escritura en Google Sheets falla por cualquier motivo
  tras haber obtenido los movimientos con éxito, el pipeline DEBE mostrar
  un mensaje que identifique el fallo como proveniente de Google Sheets, y
  DEBE terminar con el código de salida `2`.
- **FR-009**: Cuando no haya movimientos en el rango solicitado, el
  pipeline DEBE completar con éxito, dejando la pestaña con únicamente la
  fila de cabecera, y el resumen DEBE indicar cero movimientos escritos —
  esto no se considera un error.
- **FR-010**: Todas las pruebas automatizadas de este pipeline DEBEN
  mockear tanto la API de Enable Banking como la API de Google Sheets;
  ninguna prueba puede realizar una llamada de red real, y el pipeline de
  CI DEBE hacer fallar cualquier prueba que lo intente.
- **FR-011**: El pipeline DEBE reutilizar el conector ING España (IT2) y el
  escritor de Google Sheets (IT3) ya existentes, sin duplicar su lógica de
  autenticación, paginación, manejo de errores o escritura. El nombre del
  banco usado en la columna (FR-003) y en el resumen (FR-006) DEBE
  obtenerse de una constante o propiedad pública expuesta por el conector
  ING, no de un literal duplicado dentro del pipeline.
- **FR-012**: El pipeline NO DEBE mostrar ni registrar en ningún mensaje
  (resumen, log, error) ninguna credencial, JWT, `session_id` completo, ni
  JSON de cuenta de servicio.

### Entidades Clave

- **Movimiento transformado**: La combinación de un movimiento ING ya
  normalizado (por el conector, IT2) con el nombre del banco, dispuesta
  como una fila con el orden fijo de columnas del esquema (FR-003).
- **Ejecución de sincronización**: Una invocación del pipeline, delimitada
  por una fecha de inicio (día 1 del mes en curso) y una fecha de fin (la
  fecha de ejecución), con un resultado final de éxito (con un número de
  movimientos escritos) o de fallo (con el sistema responsable y el
  motivo).
- **Pestaña mensual**: La pestaña de destino en Google Sheets, nombrada
  `YYYY-MM`, que el pipeline crea o sobrescribe por completo en cada
  ejecución (comportamiento ya definido por el escritor de Sheets, IT3).

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Para un mes con un conjunto de movimientos conocido, una
  única ejecución del comando deja la pestaña `YYYY-MM` con exactamente
  esos movimientos transformados, con un 100% de acierto en el esquema de
  columnas.
- **SC-002**: Ejecutar el comando dos veces consecutivas el mismo día
  sobre el mismo conjunto de movimientos subyacente produce el mismo
  contenido final en la pestaña, con cero filas duplicadas, en el 100% de
  los casos probados.
- **SC-003**: El 100% de las ejecuciones (éxito o fallo) produce un
  mensaje final suficiente para determinar, sin inspeccionar código ni
  logs internos, qué ocurrió y, en caso de fallo, cuál de los dos sistemas
  externos fue la causa.
- **SC-004**: Ante un fallo de cualquiera de los dos sistemas externos, el
  100% de las ejecuciones termina con el código de salida distintivo de
  ese sistema (`1` para ING, `2` para Sheets), y la pestaña de destino
  nunca queda en un estado parcialmente escrito de forma silenciosa (o
  conserva su contenido previo intacto, o queda completamente sobrescrita
  — nunca una mezcla no reportada).
- **SC-005**: La suite completa de pruebas automatizadas del pipeline se
  ejecuta con cero llamadas de red reales, verificado en CI.
- **SC-006**: Una ejecución completa (obtención de movimientos y escritura
  en Sheets) se completa en menos de 2 minutos, en línea con el
  presupuesto de sincronización completa ya definido a nivel de proyecto.

## Suposiciones

- El ID del documento de Google Sheets destino (`GOOGLE_SHEET_ID`, secreto
  ya reservado desde IT1) ya está configurado; el pipeline lo lee de la
  configuración cifrada existente y no lo recibe como argumento de línea
  de comandos en esta iteración.
- El `session_id` PSD2 de ING (IT2) y el JSON de la cuenta de servicio de
  Google (IT3) ya están configurados mediante los mecanismos existentes;
  esta funcionalidad no gestiona su obtención inicial.
- "Fecha de ejecución" se interpreta como la fecha local del entorno donde
  se ejecuta el comando; no es necesario gestionar múltiples zonas
  horarias en un proyecto de un solo operador.
- Esta iteración cubre una única cuenta/entidad bancaria (ING España);
  orquestar varios bancos en una sola ejecución, con resiliencia parcial
  ante el fallo de uno de ellos, es una iteración posterior (según el
  roadmap del proyecto).
- El comando `sync` no recibe argumentos ni ofrece un modo de simulación
  ("dry-run") en esta iteración; siempre ejecuta el pipeline completo
  contra los sistemas reales (o mockeados, en tests).
- La columna de fecha reutiliza `booking_date` (fecha de liquidación) del
  conector ING; no se añade una fecha de valor PSD2 distinta en esta
  iteración (decidido en Clarifications).
