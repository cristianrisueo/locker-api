# Locker API — Especificaciones

> **Estado: inmutable durante las fases.** Este documento es la fuente de verdad de lo que hace el sistema y de cómo se
> construye. Ninguna sesión de Claude Code lo edita. Entre fases solo lo cambia el desarrollador, y cada cambio se anota
> en §16. Si el código y este documento discrepan, se para y se avisa.

## Contenido

1. Propósito
2. Alcance
3. Supuestos y limitaciones conocidas
4. Actores y roles
5. Modelo de datos
6. Invariantes
7. Comportamiento
8. Contrato HTTP
9. Arquitectura
10. Pila tecnológica
11. Estructura de ficheros
12. Configuración y ejecución
13. Entorno local, contenedores y CI
14. Estrategia de tests
15. Decisiones
16. Registro de cambios

---

## 1. Propósito

Locker API es el backend que coordina las taquillas de un edificio entre quien trae un paquete (el **transportista**) y
quien lo recoge (el **residente**). Es una versión pequeña del dominio del equipo de Buzones de Citibox.

Es el proyecto con el que el desarrollador defiende la candidatura a Senior Product Engineer (backend) y, a la vez, un
ejercicio de aprendizaje. De ahí dos reglas que mandan sobre todo lo demás:

- **Si algo no demuestra valor para la candidatura, no forma parte del proyecto.** Un campo, endpoint o capa que nadie
  usa es código muerto.
- **Lo importante es poder explicarlo.** Cada decisión de §15 tiene su motivo, y se defiende en la entrevista.

Objetivo de tiempo: unos dos días de trabajo. El núcleo son las fases F0 a F5 (`docs/plan_fases.md`); F6 (caducidad de
reservas) y F7 (despliegue en Google Cloud) se añaden después.

### 1.1 Qué debe demostrar (requisitos de la oferta)

| #   | Requisito                                                                   | Dónde se demuestra                                                          |
| --- | --------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 1   | Python y FastAPI avanzados, REST                                            | Todo el proyecto; contrato en §8                                            |
| 2   | PostgreSQL avanzado: esquema, índices, consultas, migraciones con datos     | §5, §7.3–7.5, migración de `country` (F3)                                   |
| 3   | Asincronía, eventos, segundo plano y alta concurrencia                      | `asyncio` en todo; outbox y worker (§7.10); reserva concurrente (§7.5)      |
| 4   | Integraciones y contratos: versionado, idempotencia, alta disponibilidad    | `/v1` (§8.5); `Idempotency-Key` (§7.5); dos réplicas de la API (§13)        |
| 5   | Cultura de testing: unitarios, integración y E2E                            | §14 y casos de cada fase                                                    |
| 6   | Git, GitHub y CI/CD                                                         | Una rama y una PR por fase; CI y CD en GitHub Actions, el CD hacia Google Cloud (F7, §13.5) |
| 7   | Desarrollo asistido por IA con criterio                                     | Especificaciones + plan + tests en rojo primero + revisión de cada fase     |

---

## 2. Alcance

### 2.1 Dentro

- Alta de edificios y de taquillas (con etiqueta generada) por parte del operador.
- Consulta de capacidad por talla de un edificio.
- Reserva de una taquilla por parte del transportista, idempotente y segura bajo concurrencia.
- Depósito del paquete y recogida por parte del residente con un código derivado.
- Aviso al residente al depositar, mediante outbox transaccional en PostgreSQL y un worker con reintentos.
- Caducidad de las reservas que no se depositan, por el worker.
- Autenticación por clave de API con roles (operador, transportista).
- Logs en JSON con identificador de petición.
- Entorno local en contenedores con dos réplicas de la API y un worker; tests unitarios, de integración y E2E; CI.
- Despliegue efímero en Google Cloud, con un pipeline de CD (F7, §13.5).

### 2.2 Fuera (a propósito)

| Fuera                                                         | Motivo                                                                                |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Broker de mensajes (RabbitMQ, NATS, Pub/Sub)                  | La cola vive en PostgreSQL. Se argumenta en el PDF de decisiones (§15, D9)            |
| Tabla de eventos fallidos (DLQ), columna `status` en el outbox | Un evento muerto se marca con `next_attempt_at` nulo                                  |
| Envío real de correos o SMS, webhooks al transportista        | No demuestra nada que no demuestre el log; el notificador es sustituible              |
| Evento de recogida o de reserva                               | Nadie los consume                                                                     |
| Proxy propio                                                  | Fuera de plazo; el PDF explica cómo se haría. En Google Cloud, Cloud Run ya da el HTTPS |
| Infraestructura como código (Terraform), entornos múltiples | No demuestran nada nuevo para la candidatura; la preparación se documenta con scripts |
| JWT, usuarios, contraseñas, cuenta de residente               | La clave de API cubre la integración máquina a máquina                                |
| Límite de intentos al recoger                                 | Bloquear tiene costes (bloqueo malicioso) y exige diseño de desbloqueo (supuesto A1)  |
| Listados, paginación, borrar o modificar edificios y taquillas, cancelar reservas | Ninguno demuestra nada nuevo                                       |
| Métricas, trazas y alertas                                    | Solo logs; el resto va al PDF como «qué haría con más tiempo»                         |
| Tabla de transportistas o de residentes                       | El transportista es el nombre de su clave; el residente es un texto (`recipient`)     |

---

## 3. Supuestos y limitaciones conocidas

Debilidades aceptadas. Una revisión no las reporta como defectos.

| #   | Supuesto o limitación                                                              | Consecuencia                                                                                   |
| --- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| A1  | No hay límite de intentos al recoger                                               | El código (1.000.000 de combinaciones) es adivinable por fuerza bruta a quien conozca el `id`. Diseño futuro: bloqueo temporal y limitación en el borde |
| A2  | Las claves de idempotencia no caducan ni se limpian                                | La tabla crece. En producción haría falta un job de limpieza                                   |
| A3  | La transacción queda abierta mientras se envía el aviso                            | Aceptable con el notificador de log; con un proveedor lento habría que rediseñarlo             |
| A4  | Los eventos muertos no avisan a nadie y no hay herramienta para revisarlos         | Se reactivan con una sentencia SQL documentada en el README                                    |
| A5  | El notificador de log escribe el código de recogida en claro                       | Solo es aceptable en una demostración                                                          |
| A6  | Una reserva que no se deposita caduca a los 30 minutos (F6); el transportista no conoce el plazo | El plazo (`expires_at`) no se expone en la API: el transportista descubre la caducidad al consultar y ver `EXPIRED` |
| A7  | Las claves de API están en la configuración                                        | Sin revocación individual ni rotación sin reiniciar                                            |
| A8  | El nombre del transportista distingue mayúsculas (`SEUR` ≠ `seur`)                 | Se compara tal cual                                                                            |
| A9  | El despliegue en Google Cloud es efímero y de demostración: no es un entorno de producción | Se enciende para una prueba o una entrevista y se borra. Presupuesto máximo de 5 € (§13.5) |
| A10 | En reservar, «sin taquilla» se comprueba antes que «paquete duplicado»             | Si el paquete ya tiene reserva y no quedan taquillas, la respuesta es `NO_LOCKER_AVAILABLE`    |
| A11 | Los reintentos del aviso toleran una caída de unos 30 segundos (2 + 4 + 8 + 16 s)  | Pasado ese tiempo el evento queda muerto                                                       |
| A12 | Las marcas de tiempo son las de la base de datos (`now()`)                         | Los tests no dependen del reloj de Python                                                      |
| A13 | No se exige nombre único de edificio                                               | Se pueden crear dos edificios con el mismo nombre                                              |
| A14 | Recoger dos veces da 409, mientras que depositar dos veces da 200                  | Un transportista reintenta por una respuesta perdida; un residente que ya recogió no tiene motivo |
| A15 | Dos réplicas en una misma máquina no son alta disponibilidad real                  | Prueban que el diseño no depende de un proceso concreto                                        |
| A16 | `recipient` es texto libre, sin validar su formato                                 | No hay «mis entregas» por residente                                                            |
| A17 | La instalación inicial no admite `country` en `buildings`                          | Se añade en F3 con una migración con datos, a propósito (§5.8)                                 |
| A18 | Las claves y secretos del despliegue son aleatorios y viven en Secret Manager; los de `.env.example` siguen siendo de desarrollo | Los valores de `.env.example` no son secretos reales y nunca se usan en Google Cloud |
| A19 | Las rutas inexistentes (404) y los métodos no permitidos (405) devuelven el JSON por defecto de FastAPI (`{"detail": ...}`); un error interno no controlado (500) devuelve el texto plano `Internal Server Error`, sin `X-Request-ID` | No están en el catálogo (§8.3); el contrato de `/v1` solo cubre las operaciones definidas. El traceback de un 500 se registra con `request_id` nulo, así que no se puede asociar a una petición |
| A20 | Una reserva puede recibir `NO_LOCKER_AVAILABLE` aunque haya una taquilla que va a quedar libre: `SKIP LOCKED` salta las taquillas que otra reserva en curso tiene bloqueadas | Si otra reserva retiene la única taquilla libre de esa talla y después se deshace (por ejemplo, con `DUPLICATE_PACKAGE`), esta recibe el `409` aunque la taquilla vuelva a estar libre. Complementa a A10. El cliente puede reintentar; desde F3 es seguro con la misma `Idempotency-Key`, porque una reserva fallida no la guarda (I8) |
| A21 | Un error de la propia base de datos al construir el aviso deja inutilizable la transacción del worker | El fallo no se puede apuntar: el evento no suma intentos, se reintenta en cada pausa y nunca llega a muerto. Es improbable (solo hay lecturas); un `SAVEPOINT` alrededor de construir y enviar lo evitaría |
| A22 | Un `SIGTERM` recibido durante el primer segundo y pico de vida del contenedor del worker puede perderse | Todavía no se ha instalado el manejador de señales y Docker lo termina al acabar el plazo de gracia. En ese momento no hay ningún evento en curso, así que no se pierde nada |
| A23 | El TTL de la reserva es único por despliegue (`RESERVATION_TTL_SECONDS`), no por transportista ni por edificio | Un transportista o un edificio que necesite otro plazo no puede tenerlo |
| A24 | Un cliente con una lista cerrada de estados debe tolerar valores desconocidos: `EXPIRED` es un valor nuevo en `/v1` | Añadir un valor a un enum se trata como cambio compatible (§8.5); un cliente que no lo tolere falla al ver `EXPIRED` |
| A25 | Caducar no avisa a nadie (no hay evento)                                           | Ni el transportista ni el residente reciben aviso; la caducidad solo deja una línea de log      |
| A26 | Cloud SQL usa la instancia compartida más barata (`db-f1-micro`)                   | Sin alta disponibilidad ni cobertura de SLA                                                    |
| A27 | La API desplegada es pública, protegida solo por las claves de API                 | Con A1, el código de recogida es adivinable por fuerza bruta si se conoce el `id` de la entrega (un UUID) |
| A28 | La infraestructura se prepara con scripts de bash, no de forma declarativa         | Los scripts no detectan los cambios hechos a mano en la consola de Google Cloud                |
| A29 | Las claves generadas en el despliegue no se rotan                                  | Rotarlas exige volver a ejecutar el script y redesplegar                                       |
| A30 | El dominio propio usa el *domain mapping* de Cloud Run, una función en preview y sin garantías, y el dominio y su DNS dependen de Vercel (F7b) | Google puede cambiarla o retirarla, y sin SLA. Si el DNS de Vercel falla o el dominio no se renueva, `api.lockerapi.dev` deja de responder; la URL `run.app` del servicio sigue funcionando |

---

## 4. Actores y roles

| Actor               | Cómo se identifica                       | Qué puede hacer                                                                   |
| ------------------- | ---------------------------------------- | --------------------------------------------------------------------------------- |
| **Operador**        | Clave de API con rol `operator`          | Crear edificios, dar de alta taquillas, consultar capacidad                       |
| **Transportista**   | Clave de API con rol `carrier` y nombre  | Consultar capacidad, reservar, depositar, consultar **sus** entregas              |
| **Residente**       | Sin clave: `id` de la entrega y código   | Recoger su paquete                                                                |
| **Worker** (sistema)| Proceso interno, sin API                 | Entregar los avisos pendientes del outbox y caducar las reservas que no se depositan a tiempo |

---

## 5. Modelo de datos

### 5.1 Convenciones

- **Identificadores**: UUID v7 (`uuid.uuid7()` de Python 3.14), generado en la aplicación como valor por defecto del
  modelo. Columna de tipo `Uuid`.
- **Textos**: `String(n)` con longitud máxima; las enumeraciones son `String` con `CHECK` nombrado (no tipos `ENUM` de
  PostgreSQL).
- **Fechas**: `DateTime(timezone=True)`, rellenadas con `now()` de la base de datos.
- **Nombres de restricciones**: siempre explícitos. La convención de `core/database.py` (`NAMING_CONVENTION`) se amplía
  con `"ck": "ck_%(table_name)s_%(constraint_name)s"`.
- **No hay `created_at`**: el UUID v7 ya lleva la hora de creación.

### 5.2 `buildings`

| Columna   | Tipo          | Notas                                                                                    |
| --------- | ------------- | ---------------------------------------------------------------------------------------- |
| `id`      | `Uuid`        | PK                                                                                       |
| `name`    | `String(100)` | NOT NULL. Sin restricción de unicidad (A13)                                              |
| `country` | `String(2)`   | **Se añade en F3** (migración con datos, §5.8). NOT NULL, `CHECK ck_buildings_country_format` (`country ~ '^[A-Z]{2}$'`) |

### 5.3 `lockers`

| Columna       | Tipo          | Notas                                                                |
| ------------- | ------------- | -------------------------------------------------------------------- |
| `id`          | `Uuid`        | PK                                                                   |
| `building_id` | `Uuid`        | NOT NULL. FK a `buildings.id` (`fk_lockers_building_id_buildings`)   |
| `label`       | `String(10)`  | NOT NULL. Generada: `<talla>-<nn>`, por ejemplo `M-03` (§7.3)        |
| `size`        | `String(1)`   | NOT NULL. `S`, `M` o `L`                                             |
| `status`      | `String(4)`   | NOT NULL, por defecto `FREE`. `FREE` o `BUSY`                        |

Restricciones e índices:

- `uq_lockers_building_id_label`: `UNIQUE (building_id, label)`.
- `ck_lockers_size`: `size IN ('S', 'M', 'L')`.
- `ck_lockers_status`: `status IN ('FREE', 'BUSY')`.
- `ix_lockers_free_by_size`: índice **parcial** sobre `(building_id, size)` `WHERE status = 'FREE'`. Sostiene la
  búsqueda de taquilla libre.

### 5.4 `deliveries`

| Columna         | Tipo           | Notas                                                                    |
| --------------- | -------------- | ------------------------------------------------------------------------ |
| `id`            | `Uuid`         | PK                                                                       |
| `locker_id`     | `Uuid`         | NOT NULL. FK a `lockers.id` (`fk_deliveries_locker_id_lockers`)          |
| `carrier`       | `String(100)`  | NOT NULL. Nombre del transportista, tomado de su clave de API            |
| `tracking_ref`  | `String(64)`   | NOT NULL. Referencia del paquete                                         |
| `recipient`     | `String(255)`  | NOT NULL. Texto libre (un correo o un teléfono) a quien se avisa         |
| `status`        | `String(10)`   | NOT NULL, por defecto `PENDING`. `PENDING`, `DEPOSITED`, `PICKED_UP` o `EXPIRED` (desde F6) |
| `deposited_at`  | `DateTime(tz)` | NULL hasta que se deposita                                               |
| `picked_up_at`  | `DateTime(tz)` | NULL hasta que se recoge                                                 |
| `expires_at`    | `DateTime(tz)` | **Se añade en F6.** Admite NULL. Plazo de la reserva: se fija al reservar con `now()` más `RESERVATION_TTL_SECONDS` (A12). Solo importa mientras la entrega está `PENDING`: al depositar no se toca |

Restricciones e índices:

- `ck_deliveries_status`: `status IN ('PENDING', 'DEPOSITED', 'PICKED_UP')`. En F6 se amplía a
  `status IN ('PENDING', 'DEPOSITED', 'PICKED_UP', 'EXPIRED')`.
- `ck_deliveries_pending_has_expiry` (F6): `status <> 'PENDING' OR expires_at IS NOT NULL`. Toda reserva pendiente
  tiene plazo.
- `ix_deliveries_pending_expiry` (F6): índice **parcial** sobre `(expires_at)` `WHERE status = 'PENDING'`. Sostiene la
  consulta de la caducidad (§7.13).
- `uq_deliveries_active_locker`: índice **único parcial** sobre `(locker_id)` `WHERE status IN ('PENDING', 'DEPOSITED')`.
  Una taquilla nunca tiene dos entregas activas.
- `uq_deliveries_active_package`: índice **único parcial** sobre `(carrier, tracking_ref)`
  `WHERE status IN ('PENDING', 'DEPOSITED')`. Un paquete nunca tiene dos entregas activas.

Los dos índices únicos parciales **no cambian** en F6: ya listan solo `PENDING` y `DEPOSITED`, así que una entrega
`EXPIRED` libera la taquilla y el paquete.

### 5.5 `idempotency_keys`

| Columna         | Tipo          | Notas                                                                                 |
| --------------- | ------------- | ------------------------------------------------------------------------------------- |
| `carrier`       | `String(100)` | NOT NULL. Parte de la PK                                                              |
| `key`           | `String(255)` | NOT NULL. Valor de la cabecera `Idempotency-Key`. Parte de la PK                      |
| `request_hash`  | `String(64)`  | NOT NULL. SHA-256 del cuerpo, en hexadecimal (§7.5)                                   |
| `response_body` | `JSONB`       | NULL mientras dura la transacción de la reserva; **siempre relleno una vez confirmada** |

PK: `pk_idempotency_keys` sobre `(carrier, key)`. Sin FK a `deliveries`: la respuesta guardada ya contiene el `id`.

### 5.6 `outbox_events`

| Columna           | Tipo           | Notas                                                                           |
| ----------------- | -------------- | ------------------------------------------------------------------------------- |
| `id`              | `Uuid`         | PK. Es el `event_id` que el receptor usa para ignorar repetidos                 |
| `type`            | `String(100)`  | NOT NULL. Hoy solo `delivery.deposited`                                         |
| `payload`         | `JSONB`        | NOT NULL. Hoy solo `{"delivery_id": "<uuid>"}`                                  |
| `attempts`        | `Integer`      | NOT NULL, por defecto 0. Intentos de envío fallidos                             |
| `next_attempt_at` | `DateTime(tz)` | Por defecto `now()`. **NULL = evento muerto** (agotó sus intentos)              |

Sin índices: las filas enviadas se borran, así que la tabla solo contiene pendientes y muertos.

### 5.7 Estados y transiciones

```
Entrega:   PENDING ──depositar──▶ DEPOSITED ──recoger──▶ PICKED_UP
           PENDING ──caducar────▶ EXPIRED                          (desde F6)
Taquilla:  FREE ──reservar──▶ BUSY ──recoger o caducar──▶ FREE
```

Cada transición es un `UPDATE` condicional por el estado de origen (I4). La taquilla y la entrega cambian **en la misma
transacción**:

| Operación | Taquilla         | Entrega                    | Otras escrituras                          |
| --------- | ---------------- | -------------------------- | ----------------------------------------- |
| Reservar  | `FREE` → `BUSY`  | se crea en `PENDING`       | se guarda la clave de idempotencia        |
| Depositar | —                | `PENDING` → `DEPOSITED`    | se crea el evento `delivery.deposited`    |
| Recoger   | `BUSY` → `FREE`  | `DEPOSITED` → `PICKED_UP`  | —                                         |
| Caducar   | `BUSY` → `FREE`  | `PENDING` → `EXPIRED`      | —                                         |

### 5.8 Migraciones

Una migración por tabla (salvo las que cambian una tabla existente: `country` y la caducidad), con mensaje en castellano.
Todas con `downgrade`.

| Orden | Migración                                  | Fase |
| ----- | ------------------------------------------ | ---- |
| 1     | crear `buildings`                          | F1   |
| 2     | crear `lockers`                            | F1   |
| 3     | crear `deliveries`                         | F2   |
| 4     | crear `idempotency_keys`                   | F3   |
| 5     | añadir `country` a `buildings`             | F3   |
| 6     | crear `outbox_events`                      | F4   |
| 7     | añadir caducidad a `deliveries`            | F6   |

**La migración 5 es la migración con datos** (requisito 2). Sigue el patrón expand → backfill → contract:

1. **Expand**: añadir `country` como columna nullable, para no fallar con los edificios que ya existen.
2. **Backfill**: `UPDATE buildings SET country = 'ES'`.
3. **Contract**: poner `country` en `NOT NULL` y añadir `ck_buildings_country_format`.

`downgrade`: quitar el `CHECK` y la columna. Se añade **después** de F1 a propósito, para que exista una versión
anterior con edificios que migrar. El campo `country` es opcional en la API (por defecto `ES`), así que añadirlo no
rompe a ningún cliente de `/v1` (§8.5).

**La migración 7** (F6) sigue el mismo patrón sobre `deliveries`:

1. **Expand**: añadir `expires_at` como columna nullable.
2. **Backfill**: a las filas `PENDING` existentes, `expires_at = now() + 30 minutos` (valor fijo en la migración, que no
   lee la configuración); el resto se queda en NULL.
3. **Contract**: sustituir `ck_deliveries_status` por la versión con `EXPIRED` y añadir
   `ck_deliveries_pending_has_expiry` e `ix_deliveries_pending_expiry`.

`downgrade`: quitar el índice, el `CHECK` nuevo y la columna, y restaurar el `CHECK` antiguo. Como el antiguo no admite
`EXPIRED`, antes pasa las filas `EXPIRED` a `PICKED_UP`. Es una pérdida de información asumida (se documenta en un
comentario de la migración): dejarlas en `PENDING` las haría ocupar la taquilla.

---

## 6. Invariantes

Reglas que no admiten excepciones. Cada una se escribe como una prohibición sobre lo que el código puede hacer, y
nombra el objeto de base de datos que la sostiene cuando lo hay. Las revisiones las tratan como bloqueantes.

- **I1.** Ningún código decide con un `SELECT` previo si una taquilla puede recibir una entrega: lo impide
  `uq_deliveries_active_locker`.
- **I2.** Ningún código decide con un `SELECT` previo si un paquete puede reservarse otra vez: lo impide
  `uq_deliveries_active_package`.
- **I3.** La asignación de taquilla es **una sola sentencia** (`UPDATE ... RETURNING` sobre un CTE con
  `FOR UPDATE SKIP LOCKED`). Está prohibido reservar con un `SELECT` seguido de un `UPDATE`.
- **I4.** Toda transición de estado es un `UPDATE ... WHERE status = <origen>` y se mira cuántas filas afectó. Está
  prohibido leer el estado en Python y decidir con él.
- **I5.** Los repositorios nunca llaman a `commit` ni a `rollback`. La transacción la abre el servicio con
  `async with session.begin():` como primera operación de la sesión en el caso de uso.
- **I6.** El cambio de estado de depositar y la fila del evento van en la **misma** transacción: no existe un depósito
  sin evento ni un evento sin depósito.
- **I7.** El código de recogida no se guarda, y no aparece en ninguna respuesta HTTP, en ningún evento ni en ningún log,
  salvo en el del notificador de log (A5). Se compara con `hmac.compare_digest`.
- **I8.** La clave de idempotencia se inserta antes de reservar y en la misma transacción. Solo sobreviven las claves de
  reservas que terminan bien.
- **I9.** Las claves de API y el secreto del código no se escriben en logs, respuestas ni mensajes de error. Se comparan
  en tiempo constante (`hmac.compare_digest`).
- **I10.** Todo error de un endpoint de la API tiene la forma `{"code": "...", "detail": "..."}` y nunca expone SQL,
  trazas ni mensajes del driver. Solo se devuelven los códigos del catálogo de §8.3. Excepción conocida: las rutas
  inexistentes (404) y los métodos no permitidos (405) conservan el JSON por defecto de FastAPI, y un error interno
  no controlado (500) devuelve texto plano (A19).
- **I11.** El esquema solo cambia con migraciones de Alembic. Una migración ya fusionada en `main` no se edita.
- **I12.** El alta de taquillas calcula la etiqueta con la fila del edificio bloqueada (`FOR UPDATE`) y en la misma
  transacción que inserta las taquillas.
- **I13.** El worker toma el evento con `FOR UPDATE SKIP LOCKED` dentro de la misma transacción que lo procesa y lo
  borra, y nunca procesa un evento cuyo `next_attempt_at` sea nulo o futuro.
- **I14.** La caducidad es un `UPDATE` condicional de `PENDING` a `EXPIRED`, y la liberación de la taquilla va en la
  misma transacción. Nunca queda una entrega `EXPIRED` con su taquilla `BUSY`, ni una `DEPOSITED` con su taquilla
  `FREE`.

---

## 7. Comportamiento

### 7.0 Reglas comunes

- **Transacciones.** Todo caso de uso que escribe abre `async with self._session.begin():` antes de ninguna consulta
  (I5). Un error que sale del bloque deshace todo. Las lecturas simples (capacidad, consulta de entrega) no necesitan
  `begin()`.
- **Traducción de errores de la base de datos.** El repositorio traduce el `IntegrityError` conocido a un error de
  dominio identificando la restricción por su SQLSTATE y su nombre (`23505` y `uq_deliveries_active_package` →
  `DuplicatePackageError`). Cualquier otra violación se relanza. Como el servicio es dueño de la transacción, el
  repositorio **no** hace `rollback`: el error sale del bloque `begin()` y lo hace el contexto.
- **Configuración.** Los endpoints reciben la configuración por la dependencia `get_settings`; los tests la sustituyen
  con `dependency_overrides`.
- **Sin consultas antes de `begin()`.** La dependencia de autenticación no toca la base de datos (las claves están en
  la configuración).

### 7.1 Autenticación y roles

- La cabecera `X-API-Key` se declara con `APIKeyHeader(name="X-API-Key", auto_error=False)`, para devolver nuestro
  formato de error en vez del de FastAPI.
- La dependencia `get_principal` busca la clave entre las configuradas comparando **todas** con `hmac.compare_digest`
  (tiempo constante). Devuelve un `Principal(role, name)`.
- Falta la clave o no existe → `401 UNAUTHENTICATED`.
- `require_role(...)` es una dependencia que comprueba el rol; si no corresponde → `403 FORBIDDEN`.
- Un transportista solo opera sobre **sus** entregas: si la entrega no existe o es de otro, `404 NOT_FOUND` (no `403`,
  para no revelar que existe).
- Sin clave: recoger y `/health`.

### 7.2 Alta de edificio — `POST /v1/buildings` (operador)

Cuerpo `{"name": "..."}`. Crea el edificio y responde `201` con `{"id", "name"}` (desde F3, también `country`).

### 7.3 Alta de taquillas — `POST /v1/buildings/{building_id}/lockers` (operador)

Cuerpo `{"size": "S|M|L", "quantity": 1}` (`quantity` entre 1 y 100, por defecto 1). En una transacción:

1. Bloquea la fila del edificio: `SELECT ... FROM buildings WHERE id = :id FOR UPDATE`. Si no existe, `404`. (I12.)
2. Cuenta las taquillas de ese edificio **y esa talla**: `n`.
3. Inserta `quantity` taquillas con etiquetas `<talla>-<n+1>` … `<talla>-<n+quantity>`, con el número en dos cifras
   mínimo (`M-03`, `M-100`), todas en `FREE`.

Cada talla lleva su contador: `S-01`, `M-01` y `M-02` conviven. Responde `201` con `{"lockers": [{"id", "label",
"size", "status"}, ...]}`.

Dos altas simultáneas de la misma talla se serializan por el bloqueo de la fila: una espera a la otra y las etiquetas
salen consecutivas, sin error.

### 7.4 Capacidad — `GET /v1/buildings/{building_id}/capacity` (operador o transportista)

Una sola consulta agrupada, sin parámetro de talla:

```sql
SELECT size,
       count(*) AS total,
       count(*) FILTER (WHERE status = 'FREE') AS free
FROM lockers
WHERE building_id = :building_id
GROUP BY size;
```

Responde `200` con `{"building_id", "sizes": [{"size", "total", "free"}, ...]}`, ordenado `S`, `M`, `L`, e incluyendo
solo las tallas que existen. Un edificio sin taquillas devuelve `"sizes": []`. Edificio inexistente → `404`.

### 7.5 Reservar — `POST /v1/deliveries` (transportista)

Cabecera obligatoria `Idempotency-Key` (1 a 255 caracteres; **desde F3**). Cuerpo:

```json
{ "building_id": "<uuid>", "size": "M", "tracking_ref": "ES123", "recipient": "vecino@example.com" }
```

El transportista sale de la clave de API. Todo en **una transacción**, en este orden:

1. **Huella.** SHA-256 en hexadecimal de `json.dumps(cuerpo.model_dump(mode="json"), sort_keys=True,
   separators=(",", ":"))`. Así el orden de los campos no cambia la huella.
2. **Registrar la clave.** `INSERT INTO idempotency_keys (carrier, key, request_hash) ... ON CONFLICT DO NOTHING
   RETURNING key`.
   - Si **no** devuelve fila, la clave ya existía. Como el `INSERT` espera a que termine la transacción que la creó,
     la fila está confirmada. Se lee:
     - Huella distinta → `422 IDEMPOTENCY_KEY_REUSED`.
     - Huella igual → se responde `201` con el `response_body` guardado, **sin tocar nada más**.
   - Si dos peticiones idénticas llegan a la vez, la segunda espera a la primera y recibe la misma respuesta.
3. **Edificio.** Si no existe → `404 NOT_FOUND`.
4. **Asignar taquilla.** Una sola sentencia (I3). Si no devuelve fila → `409 NO_LOCKER_AVAILABLE`. Solo talla exacta:
   nunca se asigna una talla mayor.

   ```sql
   WITH candidata AS (
       SELECT id FROM lockers
       WHERE building_id = :building_id AND size = :size AND status = 'FREE'
       ORDER BY id
       LIMIT 1
       FOR UPDATE SKIP LOCKED
   )
   UPDATE lockers SET status = 'BUSY'
   FROM candidata
   WHERE lockers.id = candidata.id
   RETURNING lockers.id, lockers.label, lockers.size;
   ```

5. **Crear la entrega** en `PENDING`, con `expires_at = now() + RESERVATION_TTL_SECONDS` (desde F6; el plazo lo
   calcula la base de datos, A12). Si salta `uq_deliveries_active_package` → `409 DUPLICATE_PACKAGE` (el repositorio
   lo traduce, §7.0). La taquilla vuelve a `FREE` por el rollback.
6. **Guardar la respuesta.** `UPDATE idempotency_keys SET response_body = :respuesta`.
7. **Confirmar** y responder `201` con la entrega (§8.4).

Consecuencias:

- Una reserva fallida no deja rastro: la fila de la clave, la entrega y el cambio de la taquilla se deshacen juntos (I8).
- La respuesta repetida es la **original**, aunque la entrega haya cambiado de estado desde entonces.
- Las claves son por transportista: dos transportistas pueden usar la misma clave sin interferir.
- Antes de F3 el endpoint no exige la cabecera y se salta los pasos 1, 2 y 6.

Las dos capas de idempotencia protegen cosas distintas: la clave devuelve **la misma respuesta** a la misma petición
repetida; el índice `uq_deliveries_active_package` **rechaza** una petición nueva sobre un paquete ya reservado.

### 7.6 Depositar — `POST /v1/deliveries/{delivery_id}/deposit` (transportista dueño)

Sin cuerpo. En una transacción:

1. `UPDATE deliveries SET status = 'DEPOSITED', deposited_at = now() WHERE id = :id AND carrier = :carrier AND status =
   'PENDING' RETURNING ...` (I4).
2. Si devolvió fila: se inserta el evento `delivery.deposited` (I6) y se responde `200` con la entrega.
3. Si no devolvió fila, se lee la entrega **del mismo transportista**:
   - No existe, o es de otro → `404 NOT_FOUND`.
   - Ya está `DEPOSITED` → `200` con la entrega tal cual, **sin segundo evento** (depositar es idempotente por estado).
   - Cualquier otro estado (`PICKED_UP` o, desde F6, `EXPIRED`) → `409 INVALID_STATE`.

### 7.7 Recoger — `POST /v1/deliveries/{delivery_id}/pickup` (sin clave)

Cuerpo `{"code": "483920"}` (exactamente seis dígitos; si no, `422`). En una transacción, en este orden:

1. La entrega no existe → `404 NOT_FOUND`.
2. No está `DEPOSITED` → `409 INVALID_STATE` (incluye recoger sin depositar, recoger dos veces y, desde F6, recoger
   una entrega `EXPIRED`).
3. El código no coincide con el derivado (§7.9) → `403 INVALID_PICKUP_CODE`. Nada cambia.
4. `UPDATE deliveries SET status = 'PICKED_UP', picked_up_at = now() WHERE id = :id AND status = 'DEPOSITED'
   RETURNING ...`. Si no afecta a ninguna fila (otra recogida simultánea ganó) → `409 INVALID_STATE`.
5. `UPDATE lockers SET status = 'FREE' WHERE id = :locker_id AND status = 'BUSY'` (I4). Si no afecta a ninguna fila,
   algo va muy mal (una entrega `DEPOSITED` siempre ocupa su taquilla) y el error inesperado deshace toda la transacción.
6. Responde `200` con la entrega.

### 7.8 Consultar — `GET /v1/deliveries/{delivery_id}` (transportista dueño)

Responde `200` con la entrega. No existe o es de otro transportista → `404 NOT_FOUND`.

Una entrega `EXPIRED` también se devuelve con `200` y `status: EXPIRED`: así descubre el transportista que su reserva
caducó (A25).

### 7.9 Código de recogida

Es **determinista y no se guarda**: se calcula a partir del secreto del servidor y del `id` de la entrega.

```
digest = HMAC-SHA256(clave = PICKUP_CODE_SECRET, mensaje = str(delivery_id))
codigo = int.from_bytes(digest[:4], "big") % 1_000_000, con ceros a la izquierda hasta 6 cifras
```

- Vive en `deliveries/pickup_code.py`, con dos funciones: `derive(secret, delivery_id) -> str` y
  `matches(secret, delivery_id, candidate) -> bool` (esta usa `hmac.compare_digest`).
- Lo usan el servicio de recogida (verifica) y el worker (lo calcula para el aviso).
- Cambiar el secreto invalida los códigos pendientes (limitación asumida).
- No hay `nonce` ni límite de intentos (A1).

### 7.10 Outbox y worker

**Evento.** Al depositar se inserta una fila de `outbox_events` con `type = "delivery.deposited"` y
`payload = {"delivery_id": "..."}`. El evento **no lleva el código ni datos del residente**: el worker los obtiene al
enviar. Las constantes y el contenido viven en `outbox/events.py`.

**Worker.** Es un proceso aparte con el mismo código: `python -m locker.outbox.worker`.

- Bucle: mientras no se pida parar, en cada vuelta ejecuta una pasada del outbox (`process_next()`) y, desde F6, una
  de caducidad (`expire_next()`, §7.13). Si ninguna de las dos tenía trabajo (las dos devuelven `False`), duerme
  `OUTBOX_POLL_INTERVAL_SECONDS`; si alguna lo tenía, vuelve a empezar sin dormir.
- Si una de las dos pasadas lanza un error inesperado (por ejemplo, la base de datos no responde o el esquema aún no
  está migrado), lo registra en el log y la trata como una pasada sin trabajo; el error no impide la otra pasada y el
  worker no muere.
- Para con `SIGINT` y `SIGTERM` terminando el evento en curso.

**`process_next() -> bool`** (`outbox/service.py`), en **una transacción** (`session.begin()`):

1. Toma un evento vencido, sin esperar a otros workers (I13):

   ```sql
   SELECT id, type, payload, attempts FROM outbox_events
   WHERE next_attempt_at <= now()
   ORDER BY next_attempt_at, id
   LIMIT 1
   FOR UPDATE SKIP LOCKED;
   ```

   Un `NULL` nunca cumple `<= now()`, así que los eventos muertos no se toman. Si no hay ninguno, devuelve `False`.
2. Construye el aviso (`Notification`): lee la entrega con su taquilla y su edificio, y calcula el código (§7.9).
3. Se lo pasa al notificador: `await notifier.send(notification)`.
4. **Éxito**: borra la fila del evento. La transacción confirma.
5. **Fallo** (cualquier `Exception` al construir o enviar): se registra en el log y, **sin relanzar** para que la
   transacción confirme, se actualiza la fila:
   - `attempts = attempts + 1`.
   - Si `attempts` alcanza `OUTBOX_MAX_ATTEMPTS` → `next_attempt_at = NULL` (**evento muerto**).
   - Si no → `next_attempt_at = now() + OUTBOX_BACKOFF_BASE_SECONDS × 2^(attempts − 1)` segundos, con `attempts` ya
     incrementado (con la base por defecto: 2, 4, 8 y 16 s).
6. Devuelve `True`.

**Notificador** (`outbox/notifier.py`). Un `Protocol` con `async def send(self, notification: Notification) -> None`.
`Notification` lleva `event_id`, `delivery_id`, `recipient`, `building_name`, `locker_label`, `pickup_code` y el texto.
La implementación real es `LogNotifier`: escribe una línea de log con el mensaje «Tu paquete está en la taquilla
{label} del edificio {building}. Tu código de recogida es {code}.» y con `event_id` y `delivery_id` como campos. Es la
única implementación de producción; el doble de test es `NotificadorFalso` (§14.3).

**Entrega «al menos una vez».** Si el worker envía y la transacción falla antes de borrar la fila, el evento se reenvía.
El mensaje lleva el `event_id` para que el receptor ignore los repetidos; en este proyecto el receptor es el doble de
test. No hay tabla de deduplicación (§2.2).

**Eventos muertos.** Se quedan en la tabla con `attempts = OUTBOX_MAX_ATTEMPTS` y `next_attempt_at` nulo. Se reactivan con:

```sql
UPDATE outbox_events SET attempts = 0, next_attempt_at = now() WHERE next_attempt_at IS NULL;
```

### 7.11 Observabilidad

- **Logs en JSON**, una línea por registro, con `ts` (ISO 8601 UTC), `level`, `logger`, `message`, `request_id` (nulo
  fuera de una petición) y los campos extra que se pasen (`event_id`, `delivery_id`...). Con `logging` de la biblioteca
  estándar y un formateador propio; `core/logging.py` expone `configure_logging(level)`, que llaman el lifespan y el
  worker.
- **Identificador de petición.** Un middleware ASGI genera un UUID v7 por petición, lo guarda en un `ContextVar` que lee
  el formateador y lo devuelve en la cabecera `X-Request-ID` de la respuesta. Siempre lo genera el servidor.
- Nunca se registran claves de API ni el secreto (I9).
- Sin métricas ni trazas (§2.2).

### 7.12 Salud — `GET /health` (sin clave)

Ejecuta `SELECT 1` con un `asyncio.timeout(2)`. Si responde → `200 {"status": "ok"}`. Si la base de datos no responde (o
tarda más de 2 s) → `503` con el error `SERVICE_UNAVAILABLE`. Un único endpoint sirve de comprobación de vida y de
disponibilidad; no hay `/health/ready`.

### 7.13 Caducidad de reservas (F6)

Una reserva que no se deposita antes de su `expires_at` caduca: la entrega pasa a `EXPIRED` y su taquilla vuelve a
`FREE`. Lo hace el worker (§7.10), como un segundo trabajo del mismo bucle. No hay evento ni aviso (A25).

**`expire_next() -> bool`** (`deliveries/expiration.py`, clase `ExpirationService`, que recibe la sesión, el repositorio
de entregas y el de taquillas), en **una transacción corta** (`session.begin()`, lo primero):

1. Toma una entrega `PENDING` vencida y la pasa a `EXPIRED` en **una sola sentencia** (I4, I14), sin esperar a otros
   workers:

   ```sql
   WITH vencida AS (
       SELECT id FROM deliveries
       WHERE status = 'PENDING' AND expires_at <= now()
       ORDER BY expires_at, id
       LIMIT 1
       FOR UPDATE SKIP LOCKED
   )
   UPDATE deliveries SET status = 'EXPIRED'
   FROM vencida
   WHERE deliveries.id = vencida.id AND deliveries.status = 'PENDING'
   RETURNING deliveries.id, deliveries.locker_id;
   ```

   Si no devuelve fila (no hay ninguna vencida), devuelve `False`.
2. Libera la taquilla devuelta con el `UPDATE` condicional de §7.7, paso 5 (`BUSY` → `FREE`), en la misma
   transacción (I14). Si no afecta a ninguna fila, algo va muy mal (una entrega `PENDING` siempre ocupa su taquilla):
   como al recoger, el error inesperado deshace toda la transacción y la entrega sigue `PENDING`.
3. Escribe una línea de log `INFO` con el `delivery_id`.
4. Devuelve `True`.

**Carrera con depositar.** Depositar (§7.6) y caducar compiten por el mismo estado de origen, `PENDING`, con un
`UPDATE` condicional (I4): gana uno. Si gana depositar, la caducidad no encuentra la fila (el `SKIP LOCKED` la salta
mientras está bloqueada, y la condición `status = 'PENDING'` la descarta después); si gana caducar, el depósito no
devuelve fila y responde `409 INVALID_STATE`.

**Dos workers.** `SKIP LOCKED` hace que cada worker tome una entrega distinta sin esperar al otro, y la condición
`status = 'PENDING'` del `UPDATE` impide que una misma entrega caduque dos veces.

---

## 8. Contrato HTTP

### 8.1 Formato de respuesta y de error

Las respuestas correctas son el JSON del recurso, sin envoltorio. Los errores tienen siempre esta forma (versión mínima
de RFC 9457):

```json
{ "code": "NO_LOCKER_AVAILABLE", "detail": "No quedan taquillas de esta talla disponibles" }
```

El manejador central convierte también el error de validación de FastAPI (que por defecto devuelve una lista) en
`VALIDATION_ERROR`, con un `detail` en texto: `campo: mensaje; campo: mensaje`.

### 8.2 Operaciones

Todas bajo `/v1`, salvo `/health`.

| Método | Ruta                                   | Quién                     | Éxito | Errores                      |
| ------ | -------------------------------------- | ------------------------- | ----- | ---------------------------- |
| POST   | `/v1/buildings`                        | operador                  | 201   | 401, 403, 422                |
| POST   | `/v1/buildings/{building_id}/lockers`  | operador                  | 201   | 401, 403, 404, 422           |
| GET    | `/v1/buildings/{building_id}/capacity` | operador, transportista   | 200   | 401, 404, 422                |
| POST   | `/v1/deliveries`                       | transportista             | 201   | 401, 403, 404, 409, 422      |
| POST   | `/v1/deliveries/{delivery_id}/deposit` | transportista dueño       | 200   | 401, 403, 404, 409, 422      |
| GET    | `/v1/deliveries/{delivery_id}`         | transportista dueño       | 200   | 401, 403, 404, 422           |
| POST   | `/v1/deliveries/{delivery_id}/pickup`  | sin clave                 | 200   | 403, 404, 409, 422           |
| GET    | `/health`                              | sin clave                 | 200   | 503                          |

Cabeceras: `X-API-Key` (autenticación), `Idempotency-Key` (solo `POST /v1/deliveries`), `X-Request-ID` (en toda
respuesta).

### 8.3 Catálogo de errores

La lista es **cerrada**: un código que no está aquí no se devuelve nunca, y cada código lo provoca al menos un test.

| Código                    | HTTP | Cuándo                                                                   | `detail`                                                |
| ------------------------- | ---- | ------------------------------------------------------------------------ | ------------------------------------------------------- |
| `UNAUTHENTICATED`         | 401  | Falta la clave de API o no es válida                                     | Falta la clave de API o no es válida                    |
| `FORBIDDEN`               | 403  | La clave es válida pero su rol no permite la operación                   | Esta clave no tiene permiso para esta operación         |
| `NOT_FOUND`               | 404  | Edificio o entrega inexistente (o entrega de otro transportista)         | Edificio {id} no encontrado / Entrega {id} no encontrada |
| `VALIDATION_ERROR`        | 422  | Datos mal formados, parámetros inválidos o falta `Idempotency-Key`       | `campo: mensaje; ...`                                   |
| `IDEMPOTENCY_KEY_REUSED`  | 422  | La misma `Idempotency-Key` con un cuerpo distinto                        | La clave ya se usó con otra petición distinta           |
| `NO_LOCKER_AVAILABLE`     | 409  | No queda taquilla libre de la talla pedida                               | No quedan taquillas de esta talla disponibles           |
| `DUPLICATE_PACKAGE`       | 409  | El paquete (transportista + referencia) ya tiene una reserva activa      | Este paquete ya tiene una reserva activa                |
| `INVALID_STATE`           | 409  | La entrega no está en un estado que permita la operación                 | La entrega no está en un estado que permita esta operación |
| `INVALID_PICKUP_CODE`     | 403  | El código de recogida no coincide                                        | Código de recogida incorrecto                           |
| `SERVICE_UNAVAILABLE`     | 503  | PostgreSQL no responde (`/health`)                                       | Base de datos no disponible                             |

### 8.4 Esquemas

**Reserva** (`POST /v1/deliveries`): cuerpo con `extra="forbid"` y `str_strip_whitespace=True`.

| Campo          | Tipo           | Regla                              |
| -------------- | -------------- | ---------------------------------- |
| `building_id`  | UUID           |                                    |
| `size`         | `"S" \| "M" \| "L"` |                               |
| `tracking_ref` | texto          | 1 a 64 caracteres                  |
| `recipient`    | texto          | 1 a 255 caracteres, sin más validación |

**Entrega** (respuesta de reservar, depositar y consultar; también la de recoger):

```json
{
  "id": "0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d70",
  "status": "PENDING",
  "building_id": "0197f3a0-1c2d-7e55-8b10-4a9d6c3e2f01",
  "locker_label": "M-03",
  "size": "M",
  "carrier": "SEUR",
  "tracking_ref": "ES123",
  "recipient": "vecino@example.com",
  "deposited_at": null,
  "picked_up_at": null
}
```

`status` es `PENDING`, `DEPOSITED`, `PICKED_UP` o, desde F6, `EXPIRED`. El plazo de la reserva (`expires_at`) **no** se
expone en ninguna respuesta. Una reserva repetida con la misma `Idempotency-Key` devuelve la respuesta original (con
`status` `PENDING`) aunque la entrega ya haya caducado (§7.5).

**Edificio**: entrada `{"name": "Edificio Sol"}` (1 a 100 caracteres) y, desde F3, `"country"` opcional (por defecto
`"ES"`, dos letras mayúsculas). Salida `{"id", "name"}` y, desde F3, `"country"`.

**Alta de taquillas**: entrada `{"size": "M", "quantity": 3}`. **Capacidad** y **recogida** (`{"code": "483920"}`) según §7.

### 8.5 Versionado

El prefijo `/v1` va en la ruta. Añadir campos opcionales, respuestas o endpoints no cambia la versión (es el caso de
`country`). Quitar o renombrar un campo, o cambiar su significado, exige `/v2`.

Un valor nuevo en un enum de la respuesta se trata como cambio compatible: es el caso de `EXPIRED` en el `status` de la
entrega (F6). Un cliente con una lista cerrada de estados debe tolerar valores desconocidos (A24).

---

## 9. Arquitectura

```
  Clientes (operador, transportista, residente)
        │ HTTP /v1
        ▼
  api-1 ┐
        ├──▶  PostgreSQL  ◀──── worker ──▶ notificador (log)
  api-2 ┘     (5 tablas: dominio, idempotencia y cola del outbox)
```

Un monolito modular con **dos procesos** del mismo código: la API (varias réplicas, sin estado en memoria) y el worker.
No hay broker, proxy ni servicios aparte.

**Despliegue en Google Cloud (F7, §13.5).** Las mismas piezas, con la misma imagen: la API es un servicio de Cloud Run
(de 0 a 2 instancias, con HTTPS de Cloud Run), el worker es un *worker pool* de Cloud Run (1 instancia), las migraciones
son un *job* de Cloud Run que se ejecuta antes de desplegar, y PostgreSQL es una instancia de Cloud SQL a la que los tres
llegan por el socket de Cloud SQL. Los secretos viven en Secret Manager y la imagen en Artifact Registry. GitHub Actions
despliega con una identidad federada, sin claves de cuenta de servicio.

```
  GitHub Actions (CD, etiqueta v*) ──federación de identidad──▶ Google Cloud (locker-api-cristian, europe-west1)
        │ imagen (SHA del commit)
        ▼
  Artifact Registry ──▶ job locker-migrate (alembic upgrade head) ──┐
                   ├──▶ servicio locker-api (Cloud Run, HTTPS) ─────┼──socket──▶ Cloud SQL locker-db (PostgreSQL 18)
                   └──▶ worker pool locker-worker ──────────────────┘
                                 ▲ secretos (Secret Manager): API_KEYS, PICKUP_CODE_SECRET, DATABASE_URL
```

### 9.1 Capas

`router` (HTTP) → `service` (lógica y transacción) → `repository` (consultas). Los `schemas` son el contrato de la API y
los `models` las tablas.

### 9.2 Reglas de dependencias

- `core/` no importa de ningún dominio.
- Un servicio puede usar **repositorios** de otros dominios (comparten la sesión de la petición); no llama a servicios
  de otros dominios.
- Sentidos permitidos: `lockers` → `buildings`; `deliveries` → `buildings`, `lockers`, `idempotency`, `outbox`;
  `outbox.service` → `deliveries` (repositorio y `pickup_code`).
- Para evitar ciclos entre módulos: `deliveries.service` solo importa `outbox.repository` y `outbox.events`;
  `outbox.service` importa `deliveries.repository` y `deliveries.pickup_code`; `deliveries.repository`,
  `outbox.repository` y `outbox.events` no importan nada del otro paquete.
- `deliveries.expiration` (F6) usa solo repositorios: `deliveries.repository` y `lockers.repository`. Nunca llama a
  servicios de otros dominios ni importa nada de `outbox`.
- Los componentes se cablean en un solo sitio: las `dependencies.py` de cada dominio y el `main.py` (y `worker.py`
  para el proceso del worker, que desde F6 cablea también `ExpirationService`).

---

## 10. Pila tecnológica

Lista **cerrada** de dependencias de Python. Añadir una dependencia no listada queda fuera de alcance en cualquier fase.
La fila «Despliegue» no son dependencias de Python: son las piezas externas del despliegue de F7 (§13.5).

| Concepto        | Elección                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------- |
| Lenguaje        | Python 3.14.8; gestor `uv` 0.12.22 (también en la imagen); backend de build `uv_build`      |
| API             | `fastapi[standard]>=0.142.2`                                                                |
| Base de datos   | PostgreSQL 18 (`postgres:18`)                                                               |
| Acceso a datos  | `sqlalchemy[asyncio]>=2.1.2` y `asyncpg>=0.31.0`                                            |
| Migraciones     | `alembic>=1.20.0`                                                                           |
| Configuración   | `pydantic-settings>=2.15.0`                                                                 |
| Desarrollo      | `pytest>=9.1.1`, `pytest-asyncio>=1.4.0`, `pytest-cov>=7.1.0`, `httpx>=0.28.1`, `testcontainers>=4.15.0`, `ruff>=0.16.10`, `mypy>=2.4.0` |
| Hash, HMAC, UUID, logs | Biblioteca estándar (`hashlib`, `hmac`, `secrets`, `uuid`, `logging`, `contextvars`) |
| Despliegue      | Google Cloud (Cloud Run, Cloud SQL, Secret Manager, Artifact Registry); GitHub Actions; bash y `gcloud` (F7) |

Las versiones mínimas son las de bookstore. Ninguna dependencia nueva.

---

## 11. Estructura de ficheros

```
locker-api/
├── .github/workflows/
│   ├── ci.yml
│   └── cd.yml
├── .vscode/settings.json
├── deploy/
│   ├── setup.sh
│   ├── domain.sh
│   └── teardown.sh
├── docs/
│   ├── especificaciones.md
│   ├── plan_fases.md
│   └── decisiones_arquitectura.pdf
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── src/locker/
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── exceptions.py
│   │   ├── exception_handlers.py
│   │   ├── security.py
│   │   ├── middleware.py
│   │   └── logging.py
│   ├── buildings/
│   ├── lockers/
│   ├── deliveries/
│   │   ├── pickup_code.py
│   │   └── expiration.py
│   ├── idempotency/
│   │   └── fingerprint.py
│   └── outbox/
│       ├── models.py
│       ├── repository.py
│       ├── events.py
│       ├── notifier.py
│       ├── service.py
│       └── worker.py
├── tests/
│   ├── unit/
│   ├── integration/
│   │   └── conftest.py
│   └── e2e/
│       └── conftest.py
├── .dockerignore  .env.example  .gitignore  .python-version
├── CLAUDE.md  README.md  Dockerfile  Makefile  compose.yml  alembic.ini
└── pyproject.toml  uv.lock
```

`buildings/`, `lockers/` y `deliveries/` tienen los siete ficheros de siempre (`__init__.py`, `router.py`, `schemas.py`,
`dependencies.py`, `service.py`, `repository.py`, `models.py`, `exceptions.py`). `idempotency/` los tiene salvo
`router.py`, `schemas.py` y `service.py` (no expone endpoints; su lógica la orquesta `deliveries.service`).

| Ruta                          | Responsabilidad                                                                   |
| ----------------------------- | --------------------------------------------------------------------------------- |
| `main.py`                     | App global, lifespan (engine, fábrica de sesiones, logs), routers bajo `/v1`, `/health`, manejadores y middleware |
| `core/config.py`              | `DatabaseSettings` (URL y eco SQL, lo único que necesitan Alembic) y `Settings` (resto), `get_settings` |
| `core/database.py`            | Engine, fábrica de sesiones, `Base` y `get_session`                               |
| `core/exceptions.py`          | `DomainError` y las familias: `NotFoundError`, `ConflictError`, `ForbiddenError`, `UnauthenticatedError`, `UnprocessableError`, `ServiceUnavailableError`. `NotFoundError`, `ForbiddenError`, `UnauthenticatedError` y `ServiceUnavailableError` llevan su `code`; en `ConflictError` y `UnprocessableError` lo pone cada error de dominio |
| `core/exception_handlers.py`  | Único sitio que traduce errores a HTTP y da forma `{code, detail}`                |
| `core/security.py`            | `Principal`, `get_principal`, `require_role`                                      |
| `core/middleware.py`          | Identificador de petición                                                         |
| `core/logging.py`             | Formateador JSON y `configure_logging`                                            |
| `buildings/`                  | Alta de edificios                                                                 |
| `lockers/`                    | Alta de taquillas, capacidad y asignación/liberación de taquilla                  |
| `deliveries/`                 | Reservar, depositar, recoger, consultar; `pickup_code.py`; `expiration.py` (`ExpirationService`, la caducidad de reservas, F6) |
| `idempotency/`                | Modelo y repositorio de claves; `fingerprint.py` (huella del cuerpo)              |
| `outbox/`                     | Modelo y repositorio de eventos; `events.py`, `notifier.py`, `service.py`, `worker.py`. Desde F6, `worker.py` ejecuta también la caducidad (conserva el nombre histórico) |
| `migrations/`                 | Alembic; `env.py` usa `DatabaseSettings`                                          |
| `deploy/setup.sh`             | Prepara Google Cloud de forma idempotente: APIs, Artifact Registry, Cloud SQL, secretos, cuentas de servicio, federación de identidad, permisos y presupuesto (F7, §13.5) |
| `deploy/domain.sh`            | Mapea el dominio propio `api.lockerapi.dev` al servicio de la API, imprime los registros DNS y espera al certificado (F7b, §13.5) |
| `deploy/teardown.sh`          | Borra lo que se factura (Cloud SQL, servicio, worker pool, job), el mapeo del dominio y los secretos; con `--unlink-billing`, desvincula la facturación (F7) |
| `.github/workflows/cd.yml`    | CD: con una etiqueta `v*` o a mano, verifica, construye la imagen, migra, despliega la API y el worker y pasa el smoke (F7) |

---

## 12. Configuración y ejecución

### 12.1 Variables de entorno

| Variable                        | Obligatoria | Por defecto | Para qué sirve                                                           |
| ------------------------------- | ----------- | ----------- | ------------------------------------------------------------------------ |
| `DATABASE_URL`                  | Sí          | —           | DSN con `+asyncpg`                                                       |
| `SQL_ECHO`                      | No          | `false`     | Muestra las consultas SQL en la consola                                  |
| `API_KEYS`                      | Sí          | —           | JSON en **una línea**: lista de `{"key", "role", "name"}` (`name` solo en `carrier`) |
| `PICKUP_CODE_SECRET`            | Sí          | —           | Secreto del HMAC del código de recogida (mínimo 32 caracteres)           |
| `OUTBOX_MAX_ATTEMPTS`           | No          | `5`         | Intentos antes de dar un evento por muerto                               |
| `OUTBOX_BACKOFF_BASE_SECONDS`   | No          | `2`         | Base de la espera entre reintentos (0 en los tests)                      |
| `OUTBOX_POLL_INTERVAL_SECONDS`  | No          | `1`         | Pausa del worker cuando no hay eventos                                   |
| `RESERVATION_TTL_SECONDS`       | No          | `1800`      | Plazo de una reserva antes de caducar (entero mayor que 0; F6)           |
| `LOG_LEVEL`                     | No          | `INFO`      | Nivel de log                                                             |

Validaciones al arrancar: `API_KEYS` no vacía; roles `operator` o `carrier`; los `carrier` llevan `name`; claves de
al menos 16 caracteres y sin repetir.

`.env.example` (valores de desarrollo; no son secretos):

```
DATABASE_URL=postgresql+asyncpg://locker:locker@localhost:5432/locker
API_KEYS=[{"key":"dev-operator-key-000000000","role":"operator"},{"key":"dev-seur-key-0000000000000","role":"carrier","name":"SEUR"},{"key":"dev-correos-key-00000000000","role":"carrier","name":"Correos Express"}]
PICKUP_CODE_SECRET=dev-pickup-secret-change-me-0000000000000
```

### 12.2 Arranque y apagado

- **API**: el lifespan lee `get_settings()` (si falta una variable obligatoria no arranca), configura los logs, crea el
  engine y la fábrica de sesiones en `app.state`, y al apagar hace `engine.dispose()`.
- **Worker**: `python -m locker.outbox.worker` hace lo mismo y arranca el bucle (§7.10).
- **Migraciones**: nunca al arrancar. Son un paso explícito (`make migrate`, o el servicio `migrate` de Compose).

---

## 13. Entorno local, contenedores y CI

### 13.1 Dockerfile

Como el de bookstore: `python:3.14.8-slim`, `uv` copiado de `ghcr.io/astral-sh/uv:0.12.22`, dependencias bloqueadas
(`uv sync --locked --no-dev`) en una capa propia, usuario sin privilegios, puerto 8000. **La misma imagen** arranca la
API (`CMD uvicorn locker.main:app`), el worker y las migraciones; solo cambia el comando.

### 13.2 `compose.yml`

El perfil `app` deja que `make up` levante solo PostgreSQL en el día a día.

| Servicio   | Definición                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------- |
| `db`       | `postgres:18`, usuario/contraseña/base `locker`, puerto 5432, volumen `pgdata`, healthcheck `pg_isready`            |
| `migrate`  | Perfil `app`. Imagen local. `alembic upgrade head` y termina. Depende de `db` sano                                  |
| `api-1`    | Perfil `app`. Imagen local, puerto 8001→8000, `env_file: .env` y `DATABASE_URL` apuntando a `db`. Healthcheck contra `/health` con Python (`urllib`; la imagen slim no trae `curl`) |
| `api-2`    | Igual que `api-1`, puerto 8002→8000                                                                                 |
| `worker`   | Perfil `app` (desde F5). Imagen local, comando `python -m locker.outbox.worker`, mismas variables de entorno         |

### 13.3 Makefile

Los comandos de bookstore (`help`, `up`, `stop`, `down`, `destroy`, `psql`, `migrate`, `migration`, `rollback`, `run`,
`check`, `test`, `test-unit`, `test-integration`, `coverage`) con los nombres adaptados (`locker`), y estos cambios:

| Comando | Qué hace |
| ------- | -------- |
| `worker` | **Nuevo** (F5). `uv run python -m locker.outbox.worker` |
| `e2e` | 1) `docker compose up -d --wait db`; 2) `docker compose --profile app run --rm migrate`; 3) `docker compose --profile app up -d --build --wait` de los servicios de aplicación; 4) `BASE_URLS=http://127.0.0.1:8001,http://127.0.0.1:8002 uv run pytest tests/e2e`; 5) para los servicios de aplicación y devuelve el código de salida de los tests |
| `smoke` | `make smoke BASE_URLS=http://...,http://...` ejecuta solo `tests/e2e/test_smoke.py` contra cada dirección |

### 13.4 CI

Idéntico al de bookstore (GitHub Actions, en push a `main` y en cada PR): `actions/checkout`, `astral-sh/setup-uv` con
caché, `uv sync --locked`, `make check`, `git diff --exit-code` (el código ya viene formateado) y `make test`. No ejecuta
E2E ni smoke.

### 13.5 Despliegue en Google Cloud (F7)

Demuestra un CD de GitHub Actions enlazado a Google Cloud, a bajo coste y de forma reproducible. El despliegue es
**efímero** (A9): se enciende para una prueba o una entrevista y se borra. No cambia el código de la aplicación.

1. **Proyecto y región.** Proyecto `locker-api-cristian` (número `953827667605`), región `europe-west1`. Los dos son
   variables al principio de los scripts.
2. **Cómputo**, con la misma imagen del `Dockerfile` (§13.1); solo cambia el comando:
   - **API**: servicio de Cloud Run `locker-api`, puerto 8000, de 0 a 2 instancias, 1 vCPU y 512 MiB. Público
     (`--allow-unauthenticated`), protegido por las claves de API de la aplicación (A27).
   - **Worker**: *worker pool* de Cloud Run `locker-worker`, 1 instancia, 1 vCPU y 512 MiB, comando
     `python -m locker.outbox.worker`.
   - **Migraciones**: *job* de Cloud Run `locker-migrate`, `alembic upgrade head`. Se ejecuta antes de desplegar, nunca
     al arrancar (§12.2).
3. **Base de datos**: Cloud SQL `locker-db`, PostgreSQL 18, edición Enterprise, tier `db-f1-micro` (A26), 10 GB SSD,
   sin alta disponibilidad, con IP pública y sin redes autorizadas. Cloud Run llega por el socket de Cloud SQL
   (`--add-cloudsql-instances`), sin conector de VPC. Base `locker` y usuario `locker` con contraseña aleatoria
   alfanumérica. La URL es
   `postgresql+asyncpg://locker:<contraseña>@/locker?host=/cloudsql/<proyecto>:<región>:<instancia>`: asyncpg recibe el
   directorio del socket como `host`.
4. **Secretos** en Secret Manager (A18): `locker-api-keys` (`API_KEYS`: una clave de operador y una de transportista
   `SEUR`, aleatorias de al menos 32 caracteres), `locker-pickup-secret` (`PICKUP_CODE_SECRET`, aleatorio de al menos 32
   caracteres) y `locker-db-url` (`DATABASE_URL`). Los genera `setup.sh` con `openssl rand` y los guarda por la entrada
   estándar, sin pasar por ficheros. Cloud Run los inyecta como variables de entorno (`--set-secrets`). Se ejecutan con
   la cuenta de servicio `locker-runtime`, que solo tiene `secretmanager.secretAccessor` y `cloudsql.client`.
5. **Imagen**: Artifact Registry, repositorio Docker `locker` en la región. La etiqueta es el SHA del commit.
6. **Autenticación del CD**: *Workload Identity Federation*. Un pool con un proveedor OIDC de
   `https://token.actions.githubusercontent.com`, con una `attribute-condition` que solo admite el repositorio
   `cristianrisueo/locker-api`. GitHub Actions actúa como la cuenta de servicio `locker-deployer`, con los roles mínimos
   para subir la imagen, ejecutar el job y desplegar el servicio y el worker pool, más `iam.serviceAccountUser` sobre
   `locker-runtime`. No hay claves de cuenta de servicio. El repositorio de GitHub guarda solo **variables** (no
   secretos): `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER` y `GCP_DEPLOYER_SA`.
7. **Scripts** (`deploy/`), con `set -euo pipefail`. Antes de hacer nada comprueban que la configuración activa de
   `gcloud` y el proyecto son los esperados:
   - `setup.sh [--yes]`: idempotente (cada recurso se comprueba antes de crearse). Se detiene si el proyecto no tiene
     facturación vinculada; activa solo las APIs necesarias; crea Artifact Registry, la instancia y la base de datos, los
     secretos, las cuentas de servicio, la federación y los permisos, y un presupuesto de 5 EUR con avisos al 50, 90 y
     100 % (si falla, avisa y sigue). Al final imprime las variables de GitHub. `--yes` evita la confirmación.
   - `teardown.sh [--yes] [--unlink-billing]`: borra Cloud SQL, el servicio (y antes su mapeo de dominio, F7b), el
     worker pool, el job y los secretos; con `--unlink-billing`, desvincula la facturación. No borra el proyecto.
8. **Pipeline** (`.github/workflows/cd.yml`, `name: CD`). Se lanza a mano (`workflow_dispatch`) o con el push de una
   etiqueta `v*`; nunca en cada push a `main`. Permisos `id-token: write` y `contents: read`. Dos trabajos:
   - `verify`: los mismos pasos que el CI (§13.4).
   - `deploy` (`needs: verify`): se autentica con la federación, construye y publica la imagen, ejecuta el job de
     migraciones y espera a que termine, despliega la API y el worker pool, calienta la API con un `curl` con reintentos
     a `/health` y pasa `make smoke BASE_URLS=<url de la API>` (el smoke no necesita `.env`).
   Usa las acciones oficiales de Google (`google-github-actions/auth` y `setup-gcloud`) con la versión fijada.
   `workflow_dispatch` solo funciona cuando el workflow ya está en la rama principal; antes, se lanza con una etiqueta.
9. **Seguridad**: la API es pública (A27) y no hay límite de intentos al recoger (A1). Las claves son aleatorias y nunca
   las de `.env.example`.
10. **Coste**: tope de 5 € con un presupuesto que avisa. Solo facturan sin parar Cloud SQL y el worker pool; la API
    escala a 0. El README documenta el coste por pieza, cómo apagar sin borrar (el worker pool a 0 instancias y Cloud SQL
    con la política de activación `never`/`always`) y cómo borrarlo todo.
11. **Dominio propio (F7b)**. La API responde también en `https://api.lockerapi.dev`. El dominio `lockerapi.dev` se
    compró en Vercel y su DNS vive allí, no en Google Cloud; la raíz queda libre para un futuro frontend en Vercel.
    - Se usa el *domain mapping* de Cloud Run (`gcloud beta run domain-mappings`, en preview, A30) en `europe-west1`:
      Google emite y renueva el certificado HTTPS. Sin balanceador de carga ni Firebase Hosting.
    - El dominio base se verifica una vez para la cuenta (Search Console, un registro `TXT` en la raíz). El mapeo pide
      un `CNAME` de `api` a `ghs.googlehosted.com.`. Son los dos únicos registros que se añaden en Vercel; los que ya
      tenía el dominio no se tocan.
    - `deploy/domain.sh` (idempotente, `set -euo pipefail`): comprueba el proyecto y la configuración y que el dominio
      está verificado, crea el mapeo si no existe, imprime los registros DNS que pide Google y espera (como mucho 30
      minutos, cada 30 s) a que el certificado esté listo y `https://api.lockerapi.dev/health` responda `200`. Si se
      agota la espera no es un error: imprime el estado y sale con un aviso. No cambia el servicio.
    - `teardown.sh` borra el mapeo, si existe, antes que el servicio. Los registros DNS y el dominio se quedan como
      están: son inofensivos, y el dominio es del desarrollador (también su renovación).

**Recursos**

| Nombre                        | Tipo                                   | Configuración                                                        |
| ----------------------------- | -------------------------------------- | -------------------------------------------------------------------- |
| `locker`                      | Repositorio de Artifact Registry       | Docker, `europe-west1`; imágenes etiquetadas con el SHA del commit   |
| `locker-db`                   | Instancia de Cloud SQL                 | PostgreSQL 18, Enterprise, `db-f1-micro`, 10 GB SSD, zonal, IP pública sin redes autorizadas; base y usuario `locker` |
| `locker-api-keys`             | Secreto                                | `API_KEYS`                                                           |
| `locker-pickup-secret`        | Secreto                                | `PICKUP_CODE_SECRET`                                                 |
| `locker-db-url`               | Secreto                                | `DATABASE_URL`                                                       |
| `locker-runtime`              | Cuenta de servicio                     | `secretmanager.secretAccessor` y `cloudsql.client`                   |
| `locker-deployer`             | Cuenta de servicio                     | Roles para publicar la imagen y desplegar; `iam.serviceAccountUser` sobre `locker-runtime`; la usa GitHub Actions |
| `locker-github` / `github`    | Pool y proveedor de identidad federada | OIDC de GitHub, solo `cristianrisueo/locker-api`                     |
| `locker-migrate`              | Job de Cloud Run                       | `alembic upgrade head`, 1 vCPU y 512 MiB, sin reintentos             |
| `locker-api`                  | Servicio de Cloud Run                  | Puerto 8000, de 0 a 2 instancias, 1 vCPU y 512 MiB, público          |
| `locker-worker`               | Worker pool de Cloud Run               | `python -m locker.outbox.worker`, 1 instancia, 1 vCPU y 512 MiB      |
| `locker-api` (presupuesto)    | Presupuesto de facturación             | 5 EUR para el proyecto, avisos al 50, 90 y 100 %                     |
| `api.lockerapi.dev`           | Mapeo de dominio de Cloud Run (F7b)    | Al servicio `locker-api`, en `europe-west1`; certificado gestionado por Google |

El job, el servicio y el worker pool los crea el pipeline, no `setup.sh`; el mapeo de dominio lo crea `domain.sh`. Los usan `locker-runtime`
y los tres secretos.

**Flujo del pipeline**

```
etiqueta v* (o workflow_dispatch) ─▶ verify: make check, git diff --exit-code, make test
                                      │ (si falla, deploy no empieza)
                                      ▼
                                    deploy: federación ─▶ docker build y push (SHA) ─▶ job locker-migrate (y espera)
                                            ─▶ servicio locker-api ─▶ worker pool locker-worker
                                            ─▶ curl /health con reintentos ─▶ make smoke BASE_URLS=<url>
```

---

## 14. Estrategia de tests

### 14.1 Niveles

Cada comportamiento se prueba en **el nivel más bajo que cace su bug**.

| Nivel       | Qué prueba                                                                                                | Dónde                 |
| ----------- | --------------------------------------------------------------------------------------------------------- | --------------------- |
| Unitario    | Lógica pura: código de recogida, huella, espera y agotamiento, validación de claves, etiquetas, errores, logs | `tests/unit/`         |
| Integración | Servicio y repositorio, o la API en el mismo proceso, contra PostgreSQL real                              | `tests/integration/`  |
| E2E         | El sistema en contenedores (imagen, lifespan, red, migraciones, dos réplicas y worker). Muy pocos          | `tests/e2e/`          |

`make test` ejecuta unitarios e integración; `uv run pytest` a secas nunca necesita el sistema levantado. La cobertura
es una señal, sin umbral.

### 14.2 Datos y aislamiento

Los de bookstore: contenedor `postgres:18` de testcontainers por sesión de pytest; esquema creado con
`alembic upgrade head` en un subproceso (con un directorio vacío como `cwd` para no leer ningún `.env`); aislamiento con
`TRUNCATE ... RESTART IDENTITY CASCADE` tras cada test; bases de datos exclusivas para los tests de migraciones;
`httpx` con `ASGITransport` y una sesión nueva por petición. Las migraciones usan solo `DatabaseSettings`, así Alembic
no exige las demás variables.

### 14.3 Dobles de prueba

Ninguno, salvo `NotificadorFalso` (en `tests/integration/`): implementa `Notifier`, **graba** cada notificación recibida
y falla (lanza una excepción) cuando se le configura. Existe porque un fallo del sistema que envía el aviso no se puede
provocar de verdad. Para la base de datos caída se usa una URL inalcanzable, no un doble.

### 14.4 Reglas

- Tests con nombre y docstring en castellano; helpers en castellano. Aserciones sobre el contenido de la respuesta.
- Sin `sleep`: la espera es configurable (0 en tests) o se modifica `next_attempt_at` en la fila.
- Concurrencia en integración: varias sesiones y `asyncio.gather`, con N ≤ 10. Entre procesos reales, solo en E2E.
- Un test de concurrencia debe fallar al quitar la protección que dice probar (se comprueba con una mutación: quitar el bloqueo o la condición del `UPDATE`). Cuando el resultado de la carrera no se puede forzar, se añade un caso determinista bajo el mismo identificador: otra transacción retiene la fila sin confirmar, se espera sin `sleep` (consultando `pg_stat_activity`) a ver la petición parada en un bloqueo, y se comprueba el resultado al confirmar.
- TDD: esqueleto, test rojo con `@pytest.mark.xfail(strict=True)`, implementación y retirada del marcador.
- Los casos obligatorios de cada fase, con identificador, están en `docs/plan_fases.md`. Cada código de error del
  catálogo (§8.3) lo provoca al menos un test, y cada invariante (§6) tiene al menos un caso que la ejercita.

---

## 15. Decisiones

Elecciones deliberadas, para que nadie las «corrija» después. Son la base del PDF `decisiones_arquitectura.pdf`.

| #   | Decisión                       | Elección                                                                                   | Alternativa descartada y motivo                                                                                       |
| --- | ------------------------------ | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| D1  | Modelo de datos y estados      | Cinco tablas; la taquilla guarda su estado (`FREE`/`BUSY`) además del de la entrega; `recipient` como texto | Calcular el estado de la taquilla desde las entregas (más simple, pero la búsqueda de taquilla libre es más cara); tabla de residentes (no hace falta) |
| D2  | Identificadores                | UUID v7                                                                                    | Enteros autoincrementales; UUID v4 (índices menos locales)                                                            |
| D3  | Política de asignación         | Solo la talla pedida; sin hueco, `409`                                                     | Asignar una talla mayor (cambia el SQL y oculta la falta de capacidad)                                                |
| D4  | Migración con datos            | `country` en `buildings`: expand → backfill → contract                                     | Una migración sin datos, que no demuestra nada                                                                        |
| D5  | Dónde vive la transacción      | El servicio, con `session.begin()`                                                         | Clase Unit of Work (el `AsyncSession` ya lo es); transacción por petición (acopla a HTTP); commit en el repositorio    |
| D6  | App de FastAPI                 | `app` global con lifespan, como bookstore                                                  | `create_app()`: nada lo pide                                                                                          |
| D7  | Idempotencia                   | Cabecera `Idempotency-Key` + índice único por paquete                                      | Solo el índice (el reintento recibiría un `409` en vez de su reserva); sin límite de caducidad de claves (A2)         |
| D8  | Código de recogida             | HMAC del `id` de la entrega con un secreto del servidor; no se guarda; sin límite de intentos | Aleatorio guardado como hash (viajaría en claro en el evento y no se podría reenviar); límite de intentos (bloqueo malicioso, sin diseño de desbloqueo) |
| D9  | Eventos                        | Outbox transaccional en PostgreSQL y worker con `SKIP LOCKED`; sin broker                  | Broker (RabbitMQ/NATS): no mejora las garantías y añade una pieza; se añadiría con varios consumidores o un volumen que el sondeo no aguante |
| D10 | Identidad                      | Clave de API por operador o transportista, como dependencia de FastAPI                     | Sin autenticación (API abierta); JWT (login, firma, caducidad: pesado para M2M)                                        |
| D11 | Contrato HTTP                  | Errores `{code, detail}` con catálogo cerrado; `/v1`; `404` para entregas ajenas           | RFC 9457 completo (campos que nadie lee); `403` para entregas ajenas (revela que existen)                             |
| D12 | Operación local                | Una imagen, Compose con dos réplicas y un worker, tres E2E y un smoke, logs JSON           | Proxy delante de las réplicas (puertos distintos bastan); métricas y trazas (fuera de plazo)                          |
| D13 | Tests                          | Tres niveles, PostgreSQL real, concurrencia probada en dos niveles                         | Dobles de la base de datos; probar la concurrencia solo con E2E (lento) o solo en integración (no cubre procesos)     |
| D14 | Salud                          | Un único `/health` que comprueba la base de datos                                          | `/health` y `/health/ready` (solo importa cuando algo reinicia contenedores según su salud)                           |
| D15 | Notificador                    | `Protocol` con `LogNotifier` y un doble de test                                            | Interfaz «por si acaso» un broker (abstracción sin uso); envío real de correos (no aporta)                            |
| D16 | Caducidad de reservas          | Columna `expires_at` y trabajo en el mismo worker con `UPDATE` condicional y `SKIP LOCKED` | Caducidad perezosa al reservar (la taquilla seguiría `BUSY` en la capacidad hasta que alguien reserve); proceso aparte (otra pieza sin necesidad); exponer `expires_at` (rompería el JSON de tests de fases cerradas) |
| D17 | Despliegue en Google Cloud     | Combinación efímera con Cloud Run (servicio, worker pool y job de migraciones) y Cloud SQL, con CD de GitHub Actions por federación de identidad | VPS con Docker Compose y Caddy (no demuestra Google Cloud); máquina virtual gratuita `e2-micro` con todo dentro (gratis, pero menos representativa y justa de memoria); FastAPI Cloud (en beta y sin procesos en segundo plano); Railway (comodidad a cambio de menos control y coste variable); CD en cada push a `main` (gastaría presupuesto sin que lo decidas) |
| D18 | Dominio propio                 | *Domain mapping* de Cloud Run para `api.lockerapi.dev`, con el dominio y el DNS en Vercel (F7b) | Balanceador de carga (coste fijo); Firebase Hosting (una pieza más); comprar el dominio en Cloud Domains (ata su vida al proyecto, que se apaga) |

---

## 16. Registro de cambios

| Fecha      | Cambio                | Motivo                                                  | Invalida |
| ---------- | --------------------- | ------------------------------------------------------- | -------- |
| 2026-10-04 | Primera versión       | Cierre de las 13 decisiones de diseño                   | —        |
| 2026-10-05 | I10, A19 y §11        | Revisión de F0: contradicción detectada por Claude Code y familias sin código propio | — |
| 2026-10-05 | A19, A20, I10 y §8.2  | Revisión de F2: el 500 es texto plano; el falso `409` por `SKIP LOCKED`; la capacidad no puede dar `403` | — |
| 2026-10-06 | §7.7, §7.10, A21, A22 y §14.4 | Cierre del núcleo (F0 a F5): la liberación de la taquilla es condicional (I4); la espera de los reintentos es 2, 4, 8 y 16 s; dos limitaciones del worker; los tests de concurrencia deben fallar sin su protección | — |
| 2026-10-06 | F6 (caducidad)        | Se añade la fase F6 tras cerrar el núcleo; redactada por Claude Code por encargo del desarrollador | A6, §1, §2.2, §4, §5.8 y §7.8 |
| 2026-10-06 | F7 (despliegue en Google Cloud) | Se añade y ejecuta la fase F7; redactada y ejecutada por Claude Code por encargo del desarrollador | A9, A18 y §2.2 |
| 2026-10-06 | F7b (dominio propio)  | La API se publica también en `api.lockerapi.dev` con el *domain mapping* de Cloud Run; redactada y ejecutada por Claude Code por encargo del desarrollador | §2.2 |
| 2026-10-07 | F7c (verificación del despliegue) | Se verifica el despliegue de extremo a extremo y se deja la evidencia | — |
