# Roadmap: Sincronización automática de movimientos bancarios a Google Sheets

## Objetivo final (reformulado)

Implementar y desplegar un proceso Python que, ejecutándose diariamente
en GitHub Actions, recupere los movimientos del mes en curso de ING,
Revolut y MyInvestor mediante Enable Banking (agregador PSD2), y los
escriba en un Google Sheet organizado en pestañas mensuales — con
notificación automática por email ante cualquier fallo parcial o total.

El sistema se considera completo cuando: (a) corre sin intervención
humana todos los días, (b) la pestaña del mes en curso refleja todos
los movimientos `BOOK` desde el día 1 hasta hoy, y (c) cualquier fallo
genera un email al propietario antes de que termine la ejecución.

---

## Grafo de dependencias

```
IT1 (skeleton + CI)
  ├── IT2 (conector ING via Enable Banking)
  │     └── IT5 (conectores Revolut + MyInvestor)
  └── IT3 (writer Google Sheets)
        └── IT4 (pipeline ING → Sheets — MVP)
              └── IT6 (notificación email)
                    └── IT7 (scheduler GitHub Actions)
```

IT2 y IT3 son desarrollables en paralelo tras IT1.
IT5 solo necesita el patrón de IT2; IT6 necesita el pipeline de IT4.

---

## Iteración 1: Skeleton del proyecto y pipeline CI

- **Valor entregado**: El repositorio tiene estructura Python lista para
  desarrollar, con CI que verifica calidad en cada push. Cualquier
  desarrollador puede reproducir el entorno local con un solo comando.
  *(Spec existente: `specs/001-project-skeleton-ci/spec.md`)*

- **Definition of Done**:
  - Estructura `src/banking/`, `tests/`, `docs/` creada
  - `requirements.txt` y `requirements-dev.txt` con dependencias pinadas
    a versión exacta
  - `ruff` (E/W/F/I/C90/N), `mypy` (estricto) y `pytest` configurados
  - GitHub Actions: pipeline pip-audit → ruff check → ruff format --check
    → mypy → pytest, disparado en push a `main` y en PRs
  - SecretStore: valores sensibles encriptados con AES-256 en `.env`
    (excluido de git); clave maestra solo como variable de entorno del SO
  - CLI: subcomando `secrets set <KEY> <VALUE>` y punto de entrada con
    mensaje de uso al invocar sin argumentos
  - `quickstart.md`: setup completo desde clone fresco en pasos lineales,
    incluyendo creación de `~/.config/banca-personal/` (directorio de
    configuración de Enable Banking)
  - CI verde

- **Dependencias**: ninguna

- **Riesgos**:
  - El diseño del SecretStore (AES-256 + clave maestra) requiere
    decisiones no triviales; si se infravaloran pueden bloquear
    iteraciones siguientes

- **Prompt para `/speckit-specify`**:

  ```
  Configura la estructura base de un proyecto Python 3.12 para un proceso
  batch de integración de datos que se ejecutará en GitHub Actions.

  El proyecto necesita:
  - Estructura de directorios estándar (src/banking/, tests/, docs/) con
    un paquete Python principal vacío listo para desarrollar
  - Gestión de dependencias con requirements.txt (producción) y
    requirements-dev.txt (herramientas de desarrollo), todas pinadas a
    versión exacta; sin rangos ni pins aproximados
  - Configuración de ruff (linting + formateo, reglas E/W/F/I/C90/N) y
    mypy (type checking estricto)
  - Framework de tests con pytest y pytest-mock
  - Pipeline de CI en GitHub Actions que ejecute en secuencia: pip-audit,
    ruff check, ruff format --check, mypy, pytest — disparado en push a
    main y en PRs; cualquier fallo detiene el pipeline en ese paso
  - Mecanismo de secretos para desarrollo local: valores sensibles
    encriptados con AES-256 en un fichero .env (excluido de git); la
    clave maestra se almacena como variable de entorno del SO, nunca en
    ningún fichero
  - CLI con subcomando `secrets set <KEY> <VALUE>` que encripta con la
    clave maestra y escribe al SecretStore, y punto de entrada que muestra
    uso disponible al invocar sin argumentos
  - quickstart.md que documente el setup completo desde un clone fresco,
    incluyendo la creación manual de ~/.config/banca-personal/ (directorio
    que usará el conector Enable Banking en iteraciones posteriores para
    almacenar eb-config.json y la clave RSA privada)

  No hay lógica de negocio en esta iteración. El valor es tener CI
  operativo y el patrón de secretos establecido para todas las
  iteraciones siguientes.
  ```

---

## Iteración 2: Conector Enable Banking (ING)

- **Valor entregado**: El sistema puede autenticarse con Enable Banking
  y recuperar los movimientos `BOOK` del mes en curso de una cuenta ING
  España. Valida la hipótesis más arriesgada: que Enable Banking soporta
  ING España y que el proceso puede operar desatendido con sesiones PSD2
  de 90-180 días.

- **Definition of Done**:
  - Componente que, dado un rango de fechas, devuelve lista de
    transacciones ING con al menos: fecha de valor, descripción, importe
    (CRDT positivo / DBIT negativo), divisa ISO 4217
  - Solo transacciones `status: BOOK`; `PDNG` e `INFO` ignorados
  - Autenticación documentada: JWT PS256 (RSA-PSS-SHA256) generado con
    clave RSA de `~/.config/banca-personal/`
  - Ciclo de vida de sesión: `session_id` PSD2 válido 90-180 días,
    leído de secretos de configuración; sin refresh tokens — al detectar
    HTTP 403 o estado `expired`, lanza error claro solicitando
    re-autorización manual
  - Paginación con `continuation_key` hasta agotar resultados
  - Respeta límite PSD2: detecta HTTP 429 y lanza error descriptivo
  - Tests unitarios con todas las llamadas HTTP mockeadas; sin llamadas
    reales en CI
  - Logging: banco, inicio, registros obtenidos, fin, estado
  - CI verde

- **Dependencias**: IT1

- **Riesgos**:
  - ⚠️ El consentimiento PSD2 inicial requiere flujo browser con ING;
    si Enable Banking no puede gestionarlo de forma semi-automatizada,
    el setup manual debe documentarse con precisión
  - ING España puede exponer solo cuentas corrientes (no fondos ni
    depósitos); limita el alcance de datos disponibles
  - El tier gratuito de Enable Banking puede tener restricciones de
    entidades o volumen no documentadas

- **Prompt para `/speckit-specify`**:

  ```
  Implementa un conector que se autentique con la API de Enable Banking
  (agregador PSD2 europeo) y recupere los movimientos de una cuenta
  ING España para un rango de fechas.

  El conector debe:
  - Autenticarse generando un JWT firmado con clave RSA privada (PS256 /
    RSA-PSS-SHA256) leída de ~/.config/banca-personal/eb-config.json
  - Leer el session_id PSD2 (válido 90-180 días) de los secretos de
    configuración; no existen refresh tokens — si recibe HTTP 403 o
    detecta estado 'expired', lanzar un error claro que indique que se
    requiere re-autorización manual (flujo browser, una sola vez)
  - Dado un rango de fechas (inicio, fin), paginar usando continuation_key
    hasta recuperar todos los registros
  - Filtrar y devolver solo transacciones con status: BOOK; ignorar
    PDNG e INFO
  - Normalizar el importe: CRDT = positivo (ingreso), DBIT = negativo
    (gasto); incluir divisa ISO 4217
  - Respetar el límite PSD2 de 4 peticiones/cuenta/día; si se supera,
    detectar HTTP 429 y lanzar un error descriptivo
  - No persistir datos; devolver la lista en memoria
  - Emitir logs estructurados: banco, inicio, número de registros,
    fin, estado (éxito o error con motivo)

  Todas las llamadas HTTP deben estar mockeadas en los tests. No se
  permiten llamadas reales en CI.

  El objetivo es validar que Enable Banking soporta ING España y que
  el proceso puede operar desatendido usando el session_id PSD2
  (90-180 días) almacenado como secreto de configuración.
  ```

---

## Iteración 3: Writer de Google Sheets

- **Valor entregado**: El sistema puede escribir (o sobreescribir)
  cualquier conjunto de filas tabulares en una pestaña de Google Sheets
  autenticándose vía cuenta de servicio. Componente reutilizable e
  independiente de la lógica bancaria.

- **Definition of Done**:
  - Autenticación con Google Sheets API via JSON de cuenta de servicio
    almacenado como secreto
  - Dado ID del documento, nombre de pestaña, cabeceras y lista de filas:
    crear la pestaña si no existe; sobreescribir completamente su
    contenido si ya existe
  - Tests unitarios con la API de Sheets mockeada; sin llamadas reales
    en CI
  - Logging: nombre de pestaña, filas escritas, duración
  - CI verde

- **Dependencias**: IT1

- **Riesgos**:
  - El JSON de la cuenta de servicio es el secreto más crítico del
    proyecto; su proceso de rotación debe documentarse desde el inicio
  - La cuota gratuita de Sheets API es generosa para uso personal pero
    debe verificarse antes de IT4

- **Prompt para `/speckit-specify`**:

  ```
  Implementa un componente que autentique con la API de Google Sheets
  mediante una cuenta de servicio de Google Cloud y escriba datos
  tabulares en una pestaña de un documento.

  El componente debe:
  - Autenticarse usando el JSON de la cuenta de servicio, almacenado
    como secreto de configuración (nunca en el código)
  - Recibir como entrada: ID del documento Google Sheets, nombre de la
    pestaña destino, fila de cabeceras y lista de filas de datos
  - Si la pestaña no existe, crearla; si ya existe, borrar su contenido
    completo y reescribir desde la primera celda
  - Emitir logs: nombre de pestaña, número de filas escritas, duración

  El componente no tiene conocimiento de entidades bancarias; recibe
  datos genéricos en forma de lista de listas. El formato de columnas
  se define en la iteración que integre este componente con los datos
  bancarios.

  Todos los tests deben mockear la API de Google. No se permiten
  llamadas reales en CI.
  ```

---

## Iteración 4: Pipeline ING → Sheets (MVP demostrable)

- **Valor entregado**: El sistema es funcional de extremo a extremo
  para ING: un único comando obtiene los movimientos del mes en curso
  y los escribe en la pestaña mensual del Sheet. Primer resultado
  completamente demostrable.

- **Definition of Done**:
  - `python -m banking sync` ejecuta el pipeline completo
  - Obtiene movimientos ING desde el día 1 del mes en curso hasta hoy
  - Esquema de columnas definido y documentado: fecha de valor, banco,
    descripción, importe, divisa (orden fijo)
  - Pestaña destino con formato `YYYY-MM` del mes en curso; idempotente
    si se ejecuta varias veces el mismo día
  - Tests de integración del pipeline completo con todos los externos
    mockeados
  - CI verde

- **Dependencias**: IT2 + IT3

- **Riesgos**:
  - La transformación entre el formato de Enable Banking y el esquema
    de columnas puede revelar campos faltantes o inconsistentes; si
    ocurre, el esquema debe ajustarse y documentarse antes de cerrar

- **Prompt para `/speckit-specify`**:

  ```
  Implementa el proceso principal de sincronización que conecta el
  conector de Enable Banking (ING) con el writer de Google Sheets.

  El proceso debe:
  - Ser invocable desde línea de comandos como punto de entrada
    principal del sistema (`python -m banking sync`)
  - Obtener los movimientos del mes en curso de la cuenta ING desde
    el día 1 del mes hasta la fecha de ejecución
  - Transformar cada movimiento al esquema tabular; columnas mínimas:
    fecha de valor, nombre del banco, descripción, importe, divisa
  - Escribir en la pestaña YYYY-MM del mes en curso; si se ejecuta
    varias veces el mismo día, el resultado debe ser idempotente
    (sobreescritura sin duplicados)
  - Emitir un resumen al finalizar: banco, movimientos escritos,
    pestaña destino, duración total

  Todos los sistemas externos (Enable Banking API y Google Sheets API)
  deben estar mockeados en los tests. No se permiten llamadas reales
  en CI.

  El objetivo es un sistema funcional demostrable para un banco, que
  sirva como base verificable para añadir más entidades.
  ```

---

## Iteración 5: Multi-banco con resiliencia parcial

- **Valor entregado**: El proceso sincroniza los tres bancos (ING,
  Revolut y MyInvestor) en una sola ejecución. Si un banco falla, los
  datos de los demás se escriben igualmente y el fallo queda registrado
  para notificación posterior.

- **Definition of Done**:
  - Conectores para Revolut y MyInvestor siguiendo el mismo contrato
    que el conector ING
  - El pipeline ejecuta los tres conectores de forma independiente y
    en secuencia
  - Fallo de un conector: error registrado en resumen de fallos, proceso
    continúa con los siguientes, datos de bancos exitosos se escriben
    en Sheets sin abortar
  - Al finalizar: resumen con bancos sincronizados (y movimientos),
    bancos fallidos (con motivo), total de movimientos escritos
  - Tests obligatorios: todos ok / un banco falla y los otros dos
    continúan / todos fallan
  - CI verde

- **Dependencias**: IT2 (patrón de conector); IT4 (pipeline a extender)

- **Riesgos**:
  - ⚠️ MyInvestor puede no estar soportado por Enable Banking; si no
    lo está, cerrar la iteración con ING + Revolut y abrir issue de
    investigación para MyInvestor
  - Revolut puede requerir un flujo PSD2 distinto al de ING
  - Cada banco requiere un `session_id` propio (consentimiento
    independiente), lo que añade complejidad al setup inicial

- **Prompt para `/speckit-specify`**:

  ```
  Extiende el pipeline de sincronización para soportar tres entidades
  bancarias de forma resiliente: ING, Revolut y MyInvestor, todas via
  Enable Banking como agregador PSD2.

  El proceso debe:
  - Ejecutar el conector de cada banco de forma independiente y en
    secuencia
  - Si un conector falla (error de API, sesión expirada — HTTP 403 o
    estado 'expired' —, rate limit HTTP 429, timeout u otro), registrar
    el error con su motivo y continuar con el siguiente banco sin abortar
    el proceso completo
  - Escribir en Google Sheets los movimientos de todos los bancos que
    respondieron correctamente en la misma ejecución
  - Producir al finalizar un resumen: qué bancos se sincronizaron (y
    cuántos movimientos), qué bancos fallaron y por qué
  - Si ningún banco responde, terminar con error sin propagar una
    excepción no controlada

  Escenarios de test obligatorios: todos ok, un banco falla y los otros
  dos continúan, todos los bancos fallan. Todos los tests deben mockear
  las APIs externas.

  El objetivo es que el proceso sea resiliente a indisponibilidades
  puntuales de una entidad bancaria sin perder los datos de las demás.
  ```

---

## Iteración 6: Notificación de errores por email

- **Valor entregado**: Cuando el proceso encuentra algún fallo (parcial
  o total), el propietario recibe un email con el detalle. Elimina la
  necesidad de revisar los logs de GitHub Actions manualmente.

- **Definition of Done**:
  - Fallo parcial (≥1 banco fallido): email con bancos fallidos, motivo
    de cada fallo, y lista de bancos que sí se sincronizaron
  - Fallo total: email indicando el error general
  - Éxito completo: no se envía ningún email
  - Canal: Gmail SMTP con contraseña de aplicación; dirección destino y
    credenciales en configuración, no en código
  - Fallo del propio envío: registrado en logs, no enmascara el error
    bancario original ni propaga una excepción nueva
  - Tests con mock de SMTP; sin envíos reales en CI
  - CI verde

- **Dependencias**: IT4 (pipeline operativo con al menos un banco)

- **Riesgos**:
  - Gmail puede bloquear el envío si la contraseña de aplicación no
    está configurada correctamente o detecta uso inusual
  - Si el proceso falla antes del paso de notificación (ej. error de
    configuración al arrancar), el email no se envía; este caso límite
    debe quedar documentado

- **Prompt para `/speckit-specify`**:

  ```
  Implementa un mecanismo de notificación por email que informe al
  propietario cuando el proceso de sincronización bancaria encuentra
  algún error.

  El comportamiento esperado:
  - Fallo parcial (≥1 banco fallido): enviar un email con el resumen
    de fallos — qué bancos fallaron, el motivo de cada fallo, y qué
    bancos se sincronizaron con éxito
  - Fallo total (ningún banco responde o error de configuración): enviar
    un email indicando el error general
  - Éxito completo: no enviar ningún email
  - Canal: Gmail SMTP con contraseña de aplicación; la dirección de
    destino y las credenciales SMTP son configuración, no código
  - Fallo del propio envío: registrar en logs y no propagar una excepción
    que enmascare el error bancario original

  Todos los tests deben mockear el cliente SMTP. No se permiten envíos
  reales en CI.

  El objetivo es que el propietario sea alertado de cualquier problema
  sin tener que acceder manualmente a los logs de GitHub Actions.
  ```

---

## Iteración 7: Scheduler en GitHub Actions (automatización completa)

- **Valor entregado**: El proceso se ejecuta automáticamente cada día
  sin intervención humana y puede dispararse manualmente desde GitHub.
  El sistema está completamente desplegado y operativo.

- **Definition of Done**:
  - Workflow con `schedule: cron` (una vez al día) y `workflow_dispatch`
  - `timeout-minutes: 10` configurado en el job
  - Todas las credenciales como GitHub Secrets; ninguna en el YAML
  - Step summary con: bancos sincronizados, movimientos escritos, fallos
    si los hay, duración total
  - Al menos una ejecución real exitosa documentada (log o screenshot)
    antes de considerar la iteración cerrada
  - CI verde (el workflow de CI sigue pasando)

- **Dependencias**: IT4 mínimo; desplegar con IT5 + IT6 ya en `main`
  para la versión completa

- **Riesgos**:
  - Las sesiones PSD2 expiran cada 90-180 días y requieren re-autorización
    manual (flujo browser); el proceso debe detectar la expiración y
    notificarla via email — se recomienda desplegar IT7 con IT6 ya en
    `main`
  - Los workflows programados de GitHub pueden retrasarse ~15 min en
    períodos de alta carga (aceptable según `context.md`)
  - La rotación de GitHub Secrets al expirar sesiones requiere proceso
    manual documentado

- **Prompt para `/speckit-specify`**:

  ```
  Configura el proceso de sincronización bancaria para que se ejecute
  automáticamente cada día mediante GitHub Actions, y pueda dispararse
  también manualmente desde la interfaz de GitHub.

  El workflow debe:
  - Ejecutarse una vez al día a una hora fija configurable
  - Admitir disparo manual mediante workflow_dispatch sin parámetros
    adicionales
  - Usar GitHub Secrets para todas las credenciales (Enable Banking
    session_id y configuración RSA, Google Sheets service account,
    Gmail SMTP); ninguna credencial en el YAML del workflow
  - Configurar timeout-minutes: 10 en el job
  - Publicar un step summary con: bancos procesados, movimientos
    escritos, errores si los hay, duración total
  - Ejecutar el mismo código que la ejecución local; sin lógica
    específica de CI/CD en el código Python

  El objetivo es que el sistema opere de forma completamente autónoma
  sin ninguna acción diaria del propietario.
  ```
