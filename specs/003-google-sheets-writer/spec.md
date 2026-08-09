# Especificación de Funcionalidad: Escritor Genérico de Google Sheets

**Rama de la funcionalidad**: `003-google-sheets-writer`

**Creado**: 2026-08-09

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Implementa un componente que autentique con la API de Google Sheets
mediante una cuenta de servicio de Google Cloud y escriba datos tabulares en una pestaña de un documento.
El componente debe: autenticarse usando el JSON de la cuenta de servicio, almacenado como secreto de
configuración (nunca en el código); recibir como entrada ID del documento Google Sheets, nombre de la
pestaña destino, fila de cabeceras y lista de filas de datos; si la pestaña no existe, crearla; si ya
existe, borrar su contenido completo y reescribir desde la primera celda; emitir logs de nombre de pestaña,
número de filas escritas y duración. El componente no tiene conocimiento de entidades bancarias; recibe
datos genéricos en forma de lista de listas. El formato de columnas se define en la iteración que integre
este componente con los datos bancarios. Todos los tests deben mockear la API de Google; no se permiten
llamadas reales en CI."

## Clarifications

### Session 2026-08-09

- Q: ¿Qué tipos de valor deben aceptarse en la fila de cabeceras y en las filas de datos? → A: Primitivos JSON-serializables (`str`, `int`, `float`, `bool`, `None`), pasados tal cual a la API de Sheets; la conversión de tipos más ricos (p. ej. `Decimal`, fechas) a texto o número es responsabilidad del proceso llamador, no del componente.
- Q: ¿Debe el componente distinguir el tipo de fallo mediante excepciones distintas, o basta con una excepción genérica y un mensaje descriptivo? → A: Excepciones distintas por categoría de causa (configuración/autenticación, documento o pestaña inaccesible, límite de cuota de la API, error de API genérico), siguiendo el mismo patrón ya usado en el conector ING (IT2), para que quien llama pueda reaccionar de forma distinta a cada caso sin parsear el mensaje.
- Q: ¿Debe fijarse un umbral numérico de duración para una escritura de este componente? → A: Sí — se hereda directamente el SLO ya definido en la constitución del proyecto ("escritura en Google Sheets por pestaña mensual < 30 segundos"), en vez de definir un umbral nuevo o dejarlo sin especificar.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Sobrescribir una pestaña existente con datos nuevos (Prioridad: P1)

Como operador de un proceso de reporting automatizado, necesito que un
conjunto de datos tabulares reemplace por completo el contenido de una
pestaña ya existente en un documento de Google Sheets, para que cada
ejecución deje la pestaña reflejando exactamente el estado actual de los
datos, sin restos de ejecuciones anteriores.

**Por qué esta prioridad**: Es el valor central del componente. Sin la
capacidad de sobrescribir de forma fiable, ningún proceso llamador puede
confiar en que la pestaña refleja el último dato sincronizado.

**Prueba independiente**: Se puede probar de forma completamente autónoma
invocando el componente con una API de Google Sheets mockeada, una pestaña
que ya contiene datos de una invocación anterior, y un nuevo conjunto de
cabeceras y filas; verificando que el contenido final de la pestaña
corresponde únicamente a la nueva invocación, comenzando en la primera
celda.

**Escenarios de Aceptación**:

1. **Dado** un documento con una pestaña existente que contiene datos de una
   ejecución previa, **Cuando** el componente se invoca con una nueva fila
   de cabeceras y una nueva lista de filas de datos para esa pestaña,
   **Entonces** el contenido previo se borra por completo y la pestaña
   queda con la fila de cabeceras en la primera fila seguida de las nuevas
   filas de datos, en el mismo orden recibido.
2. **Dado** que la nueva lista de filas de datos está vacía, **Cuando** el
   componente se invoca, **Entonces** la pestaña queda únicamente con la
   fila de cabeceras, y esto no se considera un error.
3. **Dado** que la operación se completa con éxito, **Cuando** finaliza la
   invocación, **Entonces** se emite un log con el nombre de la pestaña, el
   número de filas de datos escritas y la duración de la operación.

---

### Historia de Usuario 2 - Crear automáticamente la pestaña de destino (Prioridad: P2)

Como operador, cuando el proceso llamador indica el nombre de una pestaña
que todavía no existe en el documento (por ejemplo, una pestaña mensual
nueva), necesito que el componente la cree automáticamente y escriba los
datos en ella, para no tener que crear pestañas manualmente antes de cada
ejecución.

**Por qué esta prioridad**: Es un requisito explícito y frecuente (p. ej.
pestañas por mes), pero depende de que la escritura básica (Historia 1) ya
funcione; por eso es P2.

**Prueba independiente**: Se puede probar de forma completamente autónoma
invocando el componente con una API mockeada en la que el documento no
contiene ninguna pestaña con el nombre solicitado, y verificando que se
emite la llamada de creación de pestaña antes de la escritura de datos, y
que el resultado final es indistinguible del caso de sobrescritura de una
pestaña ya existente.

**Escenarios de Aceptación**:

1. **Dado** un documento cuyo conjunto de pestañas no incluye el nombre
   solicitado, **Cuando** el componente se invoca, **Entonces** crea una
   pestaña nueva con ese nombre y la deja con la fila de cabeceras y las
   filas de datos escritas desde la primera celda.
2. **Dado** que la pestaña solicitada ya existe, **Cuando** el componente se
   invoca, **Entonces** NO intenta crear una pestaña nueva ni duplicada;
   reutiliza la existente y sigue el comportamiento de sobrescritura de la
   Historia 1.

---

### Historia de Usuario 3 - Observabilidad de cada escritura (Prioridad: P3)

Como operador, necesito que cada invocación del componente, tanto si
termina en éxito como en fallo, deje un registro claro de qué pestaña se
vio afectada y qué ocurrió, para poder diagnosticar problemas de
sincronización sin inspeccionar código ni depurar en vivo.

**Por qué esta prioridad**: Es un requisito transversal de calidad, no una
capacidad nueva por sí misma; depende de que las Historias 1 y 2 ya
produzcan resultados sobre los que informar.

**Prueba independiente**: Se puede probar de forma completamente autónoma
forzando tanto una invocación exitosa como una fallida (por ejemplo, un
error de autenticación simulado) y verificando en ambos casos el contenido
del log emitido.

**Escenarios de Aceptación**:

1. **Dado** que la escritura se completa con éxito, **Cuando** finaliza la
   invocación, **Entonces** el log de éxito incluye como mínimo: nombre de
   la pestaña, número de filas de datos escritas y duración de la
   operación.
2. **Dado** que la escritura falla por cualquiera de las categorías de
   causa reconocidas (configuración/autenticación, documento o pestaña
   inaccesible, límite de cuota, error de API genérico), **Cuando** ocurre
   el fallo, **Entonces** se lanza una excepción específica de esa
   categoría y se emite un log de fallo que identifica la pestaña objetivo
   y el motivo, sin que el proceso termine en silencio.

---

### Casos Límite

- ¿Qué ocurre cuando el ID del documento no existe o la cuenta de servicio
  no tiene permiso de edición sobre él? → El componente DEBE fallar con un
  error claro que identifique el problema de acceso, sin crear pestañas ni
  escribir datos parciales.
- ¿Qué ocurre cuando el JSON de la cuenta de servicio almacenado como
  secreto es inválido, está incompleto o falta? → El componente DEBE fallar
  de inmediato con un error de configuración claro, antes de intentar
  ninguna llamada de red.
- ¿Qué ocurre si alguna fila de datos tiene un número de columnas distinto
  al de la fila de cabeceras? → El componente DEBE escribirla tal cual la
  recibe, sin validar, truncar ni rellenar columnas; la validación de forma
  de los datos es responsabilidad del proceso llamador.
- ¿Qué ocurre si la API de Google Sheets falla a mitad de la operación
  (por ejemplo, tras borrar el contenido previo pero antes de completar la
  escritura de los datos nuevos)? → El componente DEBE lanzar un error
  descriptivo que permita detectar el fallo y reintentar manualmente la
  invocación completa; no se garantiza atomicidad transaccional en esta
  iteración.
- ¿Qué ocurre si la API de Google Sheets responde con un error de cuota o
  límite de tasa excedido? → El componente DEBE lanzar un error descriptivo
  que identifique la causa como un límite de la API, distinto de un error
  de autenticación o de acceso; no se implementa reintento automático en
  esta iteración.

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El componente DEBE autenticarse ante la API de Google Sheets
  usando credenciales de cuenta de servicio de Google Cloud en formato
  JSON, leídas desde el mecanismo de secretos de configuración cifrados
  del proyecto; el JSON de la cuenta de servicio NO DEBE aparecer nunca
  hardcodeado en el código fuente.
- **FR-002**: El componente DEBE aceptar como entrada: el ID del documento
  de Google Sheets, el nombre de la pestaña destino, una fila de cabeceras
  (lista de valores) y una lista de filas de datos (lista de listas),
  ambas de contenido genérico sin significado conocido por el componente.
  Los valores individuales DEBEN ser primitivos JSON-serializables
  (`str`, `int`, `float`, `bool`, `None`); la conversión de tipos más
  ricos (por ejemplo `Decimal` o fechas) a una de estas formas es
  responsabilidad del proceso llamador, no de este componente.
- **FR-003**: Si la pestaña indicada no existe en el documento, el
  componente DEBE crearla antes de escribir ningún dato.
- **FR-004**: Si la pestaña indicada ya existe, el componente DEBE borrar
  la totalidad de su contenido existente antes de escribir los datos
  nuevos; NO DEBE dejar ninguna celda, fila o columna con contenido de una
  invocación anterior.
- **FR-005**: El componente DEBE escribir la fila de cabeceras como la
  primera fila de la pestaña (comenzando en la primera celda), seguida de
  las filas de datos en el mismo orden en que se recibieron, sin
  reordenarlas ni transformarlas.
- **FR-006**: El componente NO DEBE validar, truncar ni rellenar filas de
  datos cuyo número de columnas difiera del de la fila de cabeceras; las
  escribe tal cual las recibe.
- **FR-007**: Al finalizar con éxito una invocación, el componente DEBE
  emitir un registro de log estructurado que incluya: nombre de la
  pestaña, número de filas de datos escritas y duración de la operación.
- **FR-008**: Cuando una invocación falle, el componente DEBE lanzar una
  excepción distinta según la categoría de la causa — como mínimo:
  (a) configuración o autenticación inválida (credencial de cuenta de
  servicio ausente, incompleta o rechazada), (b) documento o pestaña
  inaccesible (ID inexistente o sin permiso de edición), (c) límite de
  cuota de la API de Google excedido, y (d) cualquier otro error
  inesperado de la API — y DEBE emitir en todos los casos un log de fallo
  que incluya la pestaña objetivo y el motivo; NO DEBE terminar en
  silencio ni devolver un éxito parcial.
- **FR-009**: El componente NO DEBE persistir los datos tabulares en ningún
  fichero, base de datos u otro almacenamiento local; Google Sheets es el
  único destino de la escritura.
- **FR-010**: El componente NO DEBE contener ninguna referencia a
  conceptos del dominio bancario (transacciones, bancos, divisas, cuentas);
  DEBE operar exclusivamente sobre datos tabulares genéricos (lista de
  listas), dejando la definición del formato de columnas a cargo del
  proceso llamador.
- **FR-011**: Todas las pruebas automatizadas de este componente DEBEN
  mockear cada interacción con la API de Google Sheets; ninguna prueba
  puede realizar una llamada de red real, y el pipeline de CI DEBE hacer
  fallar cualquier prueba que lo intente.
- **FR-012**: El componente NO DEBE registrar en ningún log, bajo ninguna
  circunstancia (éxito, fallo, mensaje de excepción o traza), el contenido
  del JSON de la cuenta de servicio ni ningún token de acceso derivado de
  él.

### Entidades Clave

- **Documento de Google Sheets**: Recurso externo identificado por un ID,
  compartido de antemano con la cuenta de servicio con permiso de edición;
  contiene cero o más pestañas.
- **Pestaña**: Subdivisión nombrada dentro de un documento; en cada
  invocación, o bien se crea desde cero, o bien se sobrescribe por
  completo — nunca conserva contenido de invocaciones anteriores.
- **Credencial de cuenta de servicio**: JSON de credenciales de Google
  Cloud, almacenado cifrado como secreto de configuración; es la única vía
  de autenticación del componente, sin intervención interactiva.
- **Conjunto de datos tabulares**: Una fila de cabeceras y una lista de
  filas de datos (lista de listas), cuyos valores individuales son
  primitivos JSON-serializables (`str`, `int`, `float`, `bool`, `None`),
  que el componente recibe y escribe sin interpretar su significado; el
  formato de columnas concreto lo define quien invoca el componente.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Tras cualquier invocación sobre una pestaña con contenido
  previo distinto, el contenido final de la pestaña corresponde
  exclusivamente a los datos de esa invocación (cabecera en la primera
  fila, filas de datos a continuación), sin ningún resto del contenido
  anterior, en el 100% de los casos probados.
- **SC-002**: Cuando se solicita una pestaña que no existe, queda creada y
  con los datos escritos sin ninguna intervención manual, en el 100% de
  los casos probados.
- **SC-003**: El 100% de las invocaciones (éxito o fallo) produce un
  registro de log suficiente para determinar, sin inspeccionar código, la
  pestaña afectada y, según el caso, las filas escritas o el motivo del
  fallo.
- **SC-004**: El componente puede escribir cualquier conjunto de datos
  tabulares válido (de dominio bancario o de cualquier otro) sin
  modificación de código, dado que no contiene ninguna referencia a
  conceptos bancarios.
- **SC-005**: La suite completa de pruebas automatizadas del componente se
  ejecuta con cero llamadas de red reales, verificado en CI.
- **SC-006**: Una invocación de escritura sobre una pestaña se completa en
  menos de 30 segundos, en línea con el SLO ya definido a nivel de
  proyecto para la escritura mensual en Google Sheets.

## Suposiciones

- El documento de Google Sheets ya existe y ya ha sido compartido con la
  cuenta de servicio con permiso de edición; crear el documento en sí o
  gestionar su compartición queda fuera del alcance de este componente.
- El JSON de la cuenta de servicio ya ha sido generado en Google Cloud
  Console y se almacena cifrado mediante el mecanismo de secretos ya
  existente en el proyecto (el mismo patrón usado para otros secretos).
- No se requiere ningún formato visual de celdas (colores, anchura de
  columna, tipos numéricos explícitos); Google Sheets infiere el tipo de
  cada valor a partir de su representación de texto o número.
- No se implementa reintento ni backoff automático ante límites de cuota
  de la API de Sheets en esta iteración; la necesidad de reintentos se
  evaluará antes de la iteración que integre múltiples bancos (según el
  roadmap del proyecto).
- Cada invocación opera sobre un único documento y una única pestaña;
  escribir en varios documentos o varias pestañas en una sola llamada
  queda fuera de alcance — la orquestación de múltiples escrituras es
  responsabilidad del proceso llamador.
- Un fallo a mitad de la operación (tras borrar el contenido previo, antes
  de completar la escritura de los datos nuevos) puede dejar la pestaña en
  un estado parcial; no se garantiza atomicidad transaccional en esta
  iteración, y el error lanzado debe ser suficiente para identificar y
  reintentar manualmente la operación completa.
