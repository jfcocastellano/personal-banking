# Requirements Document

## Introduction

Este documento describe los requisitos para un flujo de trabajo automatizado que obtiene los movimientos bancarios diarios de cuatro entidades (ING, Sabadell, Revolut y MyInvestor) a través de la API de Enable Banking y los persiste en archivos Excel mensuales. El sistema se ejecuta de forma desatendida mediante un cron de GitHub Actions y no dispone de interfaz de usuario; toda la salida se materializa directamente en los ficheros `.xlsx`.

El flujo completo es: autenticación OAuth con cada banco → llamada a la API de Enable Banking → normalización de los movimientos del día anterior → inserción/actualización en el Excel mensual correspondiente.

## Glossary

- **Enable Banking API**: API de terceros que proporciona acceso unificado a los datos de cuentas y transacciones de múltiples entidades bancarias mediante el estándar PSD2/Open Banking.
- **OAuth Flow**: Protocolo de autorización usado para obtener acceso delegado a las cuentas bancarias del usuario sin exponer sus credenciales.
- **Access Token**: Credencial temporal emitida por el proveedor OAuth que autoriza las llamadas a la Enable Banking API.
- **Refresh Token**: Credencial de larga duración que permite obtener nuevos Access Tokens sin reautenticación manual.
- **Transaction Fetcher**: Script Python responsable de autenticarse y recuperar los movimientos de las cuentas bancarias a través de la Enable Banking API.
- **Data Normalizer**: Componente Python responsable de transformar los datos crudos de la API al esquema normalizado interno (fecha, importe, concepto, banco).
- **Excel Writer**: Componente Python responsable de insertar o actualizar movimientos en el archivo Excel mensual usando `openpyxl`.
- **Movimiento**: Registro de una transacción bancaria con los campos normalizados: fecha, importe, concepto y banco.
- **Archivo Excel Mensual**: Fichero con nombre `movimientos_{YYYY_MM}.xlsx` que contiene los movimientos del mes correspondiente.
- **Hoja Resumen**: Hoja opcional dentro del Archivo Excel Mensual que agrega los totales del mes por banco o categoría.
- **GitHub Actions Cron**: Planificador de tareas en la plataforma GitHub Actions que dispara el flujo automáticamente cada día.
- **Callback URL**: URL local `http://localhost:8080/callback` a la que el banco redirige al usuario tras completar la autenticación OAuth.
- **Secret Store**: Mecanismo seguro (GitHub Actions Secrets / variables de entorno) para almacenar credenciales y tokens sin exponerlos en el código.
- **Process Logger**: Componente transversal responsable de escribir entradas de log con marca de tiempo, nivel y contexto en el Fichero de Log durante toda la ejecución del flujo.
- **Fichero de Log**: Archivo de texto con nombre `execution_{YYYY_MM_DD}.log` que registra cronológicamente todos los pasos y eventos del flujo de ejecución diario.
- **Nivel de Log**: Clasificación de la severidad de una entrada de log: `INFO` para pasos normales, `WARNING` para situaciones anómalas no bloqueantes y `ERROR` para fallos que impiden el procesamiento.

## Requirements

### Requirement 1: Autenticación OAuth con las entidades bancarias

**User Story:** Como propietario del sistema, quiero autenticarme de forma segura con cada entidad bancaria mediante OAuth, para que el sistema pueda acceder a mis cuentas sin almacenar mis credenciales bancarias.

#### Acceptance Criteria

1. WHEN el Transaction Fetcher inicia el flujo OAuth para una entidad bancaria, THE Transaction Fetcher SHALL redirigir al usuario a la URL de autorización de Enable Banking API correspondiente a esa entidad.
2. WHEN la entidad bancaria redirige al usuario a `http://localhost:8080/callback` con el código de autorización, THE Transaction Fetcher SHALL interceptar la petición e intercambiar el código por un Access Token y un Refresh Token. IF el Secret Store no está disponible para almacenar los tokens de forma segura, THEN THE Transaction Fetcher SHALL abortar y fallar el flujo OAuth completo para esa entidad sin persistir ningún token.
3. THE Transaction Fetcher SHALL almacenar el Access Token y el Refresh Token en el Secret Store, nunca en texto plano dentro del código fuente ni en ficheros versionados.
4. WHEN el Access Token ha expirado, THE Transaction Fetcher SHALL usar el Refresh Token para obtener un nuevo Access Token sin requerir intervención manual.
5. IF el Refresh Token ha expirado o es inválido, THEN THE Transaction Fetcher SHALL registrar un error descriptivo en los logs indicando la entidad afectada y detener el procesamiento de esa entidad sin afectar a las demás.
6. IF la solicitud de renovación del Refresh Token falla por un error de red o indisponibilidad temporal de la API, THEN THE Transaction Fetcher SHALL detener el procesamiento de esa entidad y reintentar la renovación automáticamente con retroceso exponencial, sin continuar con las transacciones de esa entidad hasta que la renovación tenga éxito.
7. THE Transaction Fetcher SHALL realizar el flujo OAuth de forma independiente para cada una de las cuatro entidades bancarias: ING, Sabadell, Revolut y MyInvestor.

---

### Requirement 2: Recuperación de movimientos del día anterior

**User Story:** Como propietario del sistema, quiero que el script recupere automáticamente los movimientos del día anterior de todas mis cuentas bancarias, para tener un registro diario actualizado sin intervención manual.

#### Acceptance Criteria

1. WHEN el GitHub Actions Cron dispara el flujo a las 00:05 (UTC), THE Transaction Fetcher SHALL calcular la fecha del día anterior como rango de consulta (`date_from` y `date_to`).
2. WHEN el Transaction Fetcher realiza la consulta de movimientos, THE Transaction Fetcher SHALL llamar al endpoint de transacciones de la Enable Banking API con el parámetro `date_from` igual a la fecha del día anterior para cada entidad bancaria.
3. THE Transaction Fetcher SHALL recuperar los movimientos de las cuatro entidades bancarias: ING, Sabadell, Revolut y MyInvestor.
4. IF la Enable Banking API devuelve un error HTTP para una entidad concreta, THEN THE Transaction Fetcher SHALL registrar el error con el código de estado y el nombre de la entidad, y continuar procesando las entidades restantes.
5. IF cualquier entidad bancaria devuelve un error HTTP durante la ejecución del cron, THEN THE GitHub Actions Cron SHALL marcar el job como `failure` al finalizar, aunque el procesamiento de las entidades restantes haya continuado.
6. IF la Enable Banking API no devuelve movimientos para una entidad en una fecha determinada, THEN THE Transaction Fetcher SHALL registrar un aviso indicando ausencia de movimientos y continuar sin error.
7. THE Transaction Fetcher SHALL completar la recuperación de movimientos de todas las entidades disponibles en una única ejecución del cron diario.

---

### Requirement 3: Normalización de los datos de movimientos

**User Story:** Como propietario del sistema, quiero que los datos crudos de la API se transformen a un esquema uniforme, para que los movimientos de todos los bancos sean comparables y puedan almacenarse de forma consistente.

#### Acceptance Criteria

1. WHEN el Data Normalizer recibe la respuesta cruda de la Enable Banking API, THE Data Normalizer SHALL extraer y mapear los campos al esquema normalizado: `fecha` (ISO 8601, YYYY-MM-DD), `importe` (valor decimal exacto), `concepto` (descripción de la transacción) y `banco` (nombre de la entidad).
2. THE Data Normalizer SHALL representar el campo `importe` usando aritmética de precisión decimal (sin punto flotante de coma binaria) para evitar errores de redondeo en valores monetarios.
3. IF un campo obligatorio del esquema normalizado (`fecha`, `importe`, `banco`) está ausente o es nulo en la respuesta de la API, THEN THE Data Normalizer SHALL registrar un aviso con el identificador del movimiento afectado y excluir ese movimiento del lote a insertar.
4. WHEN el campo `concepto` está disponible en la respuesta de la API, THE Data Normalizer SHALL usar ese valor. WHEN el campo `concepto` no está disponible en la respuesta de la API, THE Data Normalizer SHALL asignar una cadena vacía al campo `concepto` sin producir un error.
5. THE Data Normalizer SHALL preservar el signo del `importe` tal como lo devuelve la API (negativo para cargos, positivo para abonos).

---

### Requirement 4: Inserción de movimientos en el archivo Excel mensual

**User Story:** Como propietario del sistema, quiero que los movimientos normalizados se guarden en un archivo Excel organizado por mes, para poder consultarlos y analizarlos fácilmente.

#### Acceptance Criteria

1. WHEN el Excel Writer recibe un lote de movimientos normalizados, THE Excel Writer SHALL insertar cada movimiento como una nueva fila en el archivo `movimientos_{YYYY_MM}.xlsx` correspondiente al mes de la fecha del movimiento.
2. IF el archivo `movimientos_{YYYY_MM}.xlsx` del mes en curso no existe, THEN THE Excel Writer SHALL crear el fichero con una hoja principal que incluya las cabeceras: `Fecha`, `Importe`, `Concepto` y `Banco`.
3. WHEN el Excel Writer inserta movimientos, THE Excel Writer SHALL detectar filas duplicadas identificadas por la combinación única de `fecha`, `importe`, `concepto` y `banco`, insertar igualmente la fila duplicada y marcarla con el valor `DUPLICATE` en una columna adicional llamada `Estado`. WHEN el Excel Writer inserta movimientos no duplicados, THE Excel Writer SHALL marcar esas filas con el valor `NORMAL` en la columna `Estado`.
4. THE Excel Writer SHALL conservar todas las filas existentes en el archivo Excel mensual al añadir nuevos movimientos, sin sobrescribir ni eliminar datos previos.
5. WHEN el Excel Writer finaliza la escritura con éxito, THE Excel Writer SHALL guardar y cerrar el fichero `.xlsx` correctamente para garantizar la integridad del archivo. IF la escritura fue interrumpida o no completada, THEN THE Excel Writer SHALL no guardar ni cerrar el fichero.

---

### Requirement 5: Hoja resumen mensual (opcional)

**User Story:** Como propietario del sistema, quiero que el archivo Excel incluya una hoja de resumen con los totales del mes por banco, para tener una visión rápida de mis finanzas mensuales.

#### Acceptance Criteria

1. WHERE la generación de hoja resumen está habilitada, THE Excel Writer SHALL crear o actualizar una hoja llamada `Resumen` dentro del archivo `movimientos_{YYYY_MM}.xlsx` después de insertar los movimientos del día.
2. WHERE la generación de hoja resumen está habilitada, THE Excel Writer SHALL calcular el total de ingresos y el total de gastos por banco usando aritmética decimal exacta.
3. WHERE la generación de hoja resumen está habilitada, WHEN el Excel Writer recalcula la hoja `Resumen`, THE Excel Writer SHALL actualizar los totales con todos los movimientos acumulados en el mes hasta la fecha, no solo los del día en curso.

---

### Requirement 6: Ejecución diaria automatizada mediante GitHub Actions

**User Story:** Como propietario del sistema, quiero que el flujo se ejecute automáticamente cada día sin intervención manual, para no tener que lanzar el script de forma manual.

#### Acceptance Criteria

1. THE GitHub Actions Cron SHALL disparar el flujo de trabajo completo una vez al día a las 00:05 UTC.
2. THE GitHub Actions Cron SHALL ejecutar el Transaction Fetcher, el Data Normalizer y el Excel Writer en secuencia dentro de un único job.
3. WHEN el flujo finaliza, THE GitHub Actions Cron SHALL marcar el job como `success` únicamente si los tres pasos de procesamiento —Transaction Fetcher, Data Normalizer y Excel Writer— se ejecutaron y completaron sin errores. IF alguno de los tres pasos no completó su ejecución, THEN THE GitHub Actions Cron SHALL marcar el job como `failure`.
4. IF cualquier paso del flujo produce un error no recuperable, THEN THE GitHub Actions Cron SHALL marcar el job como `failure` y registrar el error en los logs de la ejecución. IF el registro de logs falla, THE GitHub Actions Cron SHALL igualmente marcar el job como `failure`.
5. THE GitHub Actions Cron SHALL leer todas las credenciales y tokens necesarios exclusivamente desde GitHub Actions Secrets, sin leer ningún valor sensible desde el código fuente ni desde ficheros versionados.

---

### Requirement 7: Seguridad y gestión de credenciales

**User Story:** Como propietario del sistema, quiero que todas las credenciales y tokens estén protegidos, para que mis datos financieros no queden expuestos en el repositorio ni en los logs.

#### Acceptance Criteria

1. THE Transaction Fetcher SHALL leer las credenciales de cliente OAuth (client ID, client secret) y los tokens de acceso exclusivamente desde variables de entorno o desde el Secret Store, nunca desde ficheros versionados.
2. THE Transaction Fetcher SHALL transmitir todos los datos hacia y desde la Enable Banking API exclusivamente sobre conexiones HTTPS.
3. IF un token, credencial u otro secreto no está disponible, tiene un formato inválido o ha expirado en el entorno de ejecución, THEN THE Transaction Fetcher SHALL registrar un error descriptivo sin revelar el valor esperado de la credencial, detener inmediatamente la ejecución del flujo y garantizar que ningún valor de credencial quede expuesto durante el propio proceso de gestión del error.
4. THE Transaction Fetcher SHALL garantizar que ningún valor de Access Token, Refresh Token ni credencial bancaria aparezca en texto plano en los logs de ejecución, independientemente de si las credenciales son válidas, inválidas o están ausentes.

---

### Requirement 8: Registro del proceso en fichero de log

**User Story:** Como propietario del sistema, quiero que todos los pasos del flujo de ejecución queden registrados en un fichero de log con marca de tiempo y nivel de severidad, para poder conocer en todo momento el estado del proceso y diagnosticar cualquier incidencia.

#### Acceptance Criteria

1. WHEN el flujo de ejecución se inicia, THE Process Logger SHALL crear o abrir en modo de adición (append) el Fichero de Log con nombre `execution_{YYYY_MM_DD}.log` correspondiente a la fecha de ejecución, de modo que las re-ejecuciones del mismo día no sobrescriban las entradas anteriores.
2. WHEN cualquier componente del flujo —Transaction Fetcher, Data Normalizer o Excel Writer— inicia o completa un paso de procesamiento, THE Process Logger SHALL escribir una entrada de nivel `INFO` en el Fichero de Log que incluya la marca de tiempo en formato ISO 8601, el nombre del componente, la entidad bancaria afectada (cuando aplique) y una descripción del paso ejecutado.
3. WHEN el Transaction Fetcher, el Data Normalizer o el Excel Writer registran un aviso según los criterios definidos en los Requisitos 1–7, THE Process Logger SHALL escribir una entrada de nivel `WARNING` en el Fichero de Log, incluyendo marca de tiempo en formato ISO 8601, nombre del componente, entidad bancaria afectada y descripción del aviso.
4. WHEN el Transaction Fetcher, el Data Normalizer o el Excel Writer registran un error según los criterios definidos en los Requisitos 1–7, THE Process Logger SHALL escribir una entrada de nivel `ERROR` en el Fichero de Log, incluyendo marca de tiempo en formato ISO 8601, nombre del componente, entidad bancaria afectada y descripción del error, sin revelar valores de credenciales o tokens.
5. WHEN el flujo de ejecución finaliza, THE Process Logger SHALL escribir una entrada de nivel `INFO` en el Fichero de Log indicando el resultado final del flujo (`success` o `failure`) y la marca de tiempo de finalización en formato ISO 8601.
6. THE GitHub Actions Cron SHALL publicar el Fichero de Log como artefacto de la ejecución con un período de retención de 90 días, para que el propietario del sistema pueda descargarlo y consultarlo desde la interfaz de GitHub Actions. IF la creación del Fichero de Log falló durante la ejecución, THE GitHub Actions Cron SHALL publicar igualmente un artefacto, aunque esté vacío o ausente.
7. IF la escritura en el Fichero de Log falla durante la ejecución, THEN THE Process Logger SHALL emitir ese mensaje de log y todos los mensajes de log subsiguientes por la salida estándar de error (`stderr`) y continuar la ejecución del flujo sin interrumpirlo. IF la salida por `stderr` también falla, THEN THE Process Logger SHALL continuar la ejecución del flujo, priorizando la disponibilidad del sistema sobre la completitud del registro.