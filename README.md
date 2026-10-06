# Locker API

API de taquillas para paquetería: un transportista reserva una taquilla de un edificio, deposita el paquete y el residente lo recoge con un código. Python 3.14, FastAPI y PostgreSQL.

Qué hace el sistema y cómo se construye está en [`docs/especificaciones.md`](docs/especificaciones.md); el orden de construcción, por fases, en [`docs/plan_fases.md`](docs/plan_fases.md).

> **Estado: F7 (núcleo completo, caducidad de reservas y despliegue en Google Cloud).** Sobre la base de F0 (errores, logs, identificador de petición, `/health`, contenedores con dos réplicas, tests y CI) hay claves de API con roles, alta de edificios (con país), alta de taquillas con etiqueta generada, consulta de capacidad y **reserva de taquilla** segura bajo concurrencia, también entre réplicas, con **`Idempotency-Key` obligatoria**: repetir una reserva devuelve la misma respuesta. `country` se añadió a `buildings` con una **migración con datos**. El **ciclo de la entrega** está completo: el transportista deposita (y se apunta el evento del aviso en la misma transacción), consulta su entrega, y el residente recoge con un **código derivado** que no se guarda. Un **worker** (proceso aparte con el mismo código) envía el aviso del depósito al residente desde el outbox, con reintentos y espera creciente; los avisos que agotan sus intentos quedan como eventos muertos y se reactivan con una sentencia SQL. El mismo worker **caduca las reservas** que no se depositan a tiempo (30 minutos por defecto): pasan a `EXPIRED` y su taquilla vuelve a quedar libre. El sistema se **despliega en Google Cloud** desde GitHub Actions (Cloud Run y Cloud SQL) y se borra con un script: es un despliegue efímero, de demostración.

## Stack

| Pieza                          | Para qué se usa                                                         |
| ------------------------------ | ----------------------------------------------------------------------- |
| Python 3.14 y uv               | Lenguaje, entorno virtual y dependencias (`pyproject.toml` + `uv.lock`) |
| FastAPI y Uvicorn              | Framework web y servidor ASGI                                           |
| Pydantic y pydantic-settings   | Contrato de la API y configuración desde variables de entorno           |
| SQLAlchemy 2 (async) y asyncpg | Acceso a PostgreSQL                                                     |
| Alembic                        | Migraciones del esquema                                                 |
| PostgreSQL 18 en Docker        | Base de datos (`compose.yml`)                                           |
| pytest y testcontainers        | Tests unitarios, de integración contra PostgreSQL real, y E2E           |
| Ruff y mypy (strict)           | Formateo, linter y comprobación de tipos                                |

## Puesta en marcha desde cero

Necesitas [uv](https://docs.astral.sh/uv/) y Docker en marcha. Los puertos 5432 (PostgreSQL), 8000 (`make run`) y 8001 y 8002 (las réplicas de `make e2e`) deben estar libres.

```bash
cp .env.example .env   # variables de entorno de desarrollo (no son secretos)
uv sync                # instala Python 3.14.8 si hace falta y las dependencias en .venv
make up                # levanta PostgreSQL en Docker
make migrate           # crea las tablas
make run               # arranca la API en http://127.0.0.1:8000 (documentación en /docs)
make worker            # en otra terminal: arranca el worker que envía los avisos y caduca reservas (Ctrl-C para pararlo)
```

Comprueba que responde:

```bash
curl -i localhost:8000/health
```

Responde `200 {"status": "ok"}` con una cabecera `X-Request-ID`. Si paras la base de datos (`make stop`), responde `503` con `{"code": "SERVICE_UNAVAILABLE", "detail": "Base de datos no disponible"}`.

### Variables de entorno

| Variable       | Obligatoria | Por defecto | Para qué sirve                                                   |
| -------------- | ----------- | ----------- | ---------------------------------------------------------------- |
| `DATABASE_URL` | Sí          | —           | DSN de PostgreSQL. El `+asyncpg` es obligatorio (driver asíncrono) |
| `SQL_ECHO`     | No          | `false`     | Muestra las consultas SQL en la consola                          |
| `LOG_LEVEL`    | No          | `INFO`      | Nivel mínimo de los logs                                         |
| `API_KEYS`     | Sí          | —           | Claves de API, en JSON de **una línea** (ver abajo)               |
| `PICKUP_CODE_SECRET` | Sí    | —           | Secreto con el que se calcula el código de recogida (mínimo 32 caracteres) |
| `OUTBOX_MAX_ATTEMPTS` | No   | `5`         | Intentos de envío de un aviso antes de dar el evento por muerto  |
| `OUTBOX_BACKOFF_BASE_SECONDS` | No | `2`   | Base de la espera entre reintentos: 2, 4, 8 y 16 segundos (0 en los tests) |
| `OUTBOX_POLL_INTERVAL_SECONDS` | No | `1`  | Pausa del worker cuando no tiene trabajo (ni avisos que enviar ni reservas que caducar) |
| `RESERVATION_TTL_SECONDS` | No  | `1800`      | Plazo de una reserva para depositar, en segundos (entero mayor que 0); pasado, caduca |

Se leen del entorno y, si no están, del `.env`. Si falta una obligatoria, ni la API ni el worker arrancan (los dos leen la misma configuración). Alembic solo necesita `DATABASE_URL`: migrar no exige las claves ni el secreto. Si tu `.env` es anterior a F4, añádele `PICKUP_CODE_SECRET` (el valor de desarrollo está en `.env.example`): sin ella no arrancan ni `make run` ni las réplicas de `make e2e`.

### Claves de API

Cada operación de `/v1` exige la cabecera `X-API-Key`. Las claves y sus roles están en `API_KEYS`, una lista de `{"key", "role", "name"}`:

| Rol        | Qué puede hacer                                         | `name`                                                   |
| ---------- | ------------------------------------------------------- | -------------------------------------------------------- |
| `operator` | Crear edificios, dar de alta taquillas, ver capacidad   | No hace falta                                            |
| `carrier`  | Ver capacidad, reservar, depositar y consultar **sus** entregas | Obligatorio: es el nombre del transportista (`SEUR`) |

Al arrancar se valida la lista: no puede estar vacía, los roles son `operator` o `carrier`, cada `carrier` lleva `name` y las claves tienen al menos 16 caracteres y no se repiten. Si algo falla, la API no arranca y el error no muestra ninguna clave.

`.env.example` trae tres claves de desarrollo (no son secretos): `dev-operator-key-000000000` (operador), `dev-seur-key-0000000000000` (SEUR) y `dev-correos-key-00000000000` (Correos Express).

Recoger no lleva clave: el residente se identifica con el id de la entrega y su código. Sin clave, o con una que no existe, la respuesta es `401 UNAUTHENTICATED`; con una clave válida de un rol sin permiso, `403 FORBIDDEN`. La clave se compara con todas las configuradas en tiempo constante (`hmac.compare_digest`) y nunca aparece en logs ni respuestas.

### Ejemplo de uso

Con la API en marcha (`make run`):

```bash
OPERADOR="X-API-Key: dev-operator-key-000000000"

# El operador crea un edificio
curl -s -X POST localhost:8000/v1/buildings -H "$OPERADOR" -H 'Content-Type: application/json' \
  -d '{"name": "Edificio Sol"}'
# {"id":"01a10b7b-629d-73d8-b02f-8994048149d7","name":"Edificio Sol","country":"ES"}   # country es opcional: ES por defecto

EDIFICIO=01a10b7b-629d-73d8-b02f-8994048149d7   # el id que ha devuelto

# Da de alta 3 taquillas M: las etiquetas se generan por talla (M-01, M-02, M-03)
curl -s -X POST localhost:8000/v1/buildings/$EDIFICIO/lockers -H "$OPERADOR" -H 'Content-Type: application/json' \
  -d '{"size": "M", "quantity": 3}'
# {"lockers":[{"id":"...","label":"M-01","size":"M","status":"FREE"},{...,"label":"M-02",...},{...,"label":"M-03",...}]}

# Un transportista consulta la capacidad
curl -s localhost:8000/v1/buildings/$EDIFICIO/capacity -H "X-API-Key: dev-seur-key-0000000000000"
# {"building_id":"01a10b7b-629d-73d8-b02f-8994048149d7","sizes":[{"size":"M","total":3,"free":3}]}

# SEUR reserva una taquilla M para su paquete ES123: el transportista sale de la clave, no del cuerpo.
# Idempotency-Key es obligatoria: identifica esta petición (sin ella, 422 VALIDATION_ERROR)
curl -s -X POST localhost:8000/v1/deliveries -H "X-API-Key: dev-seur-key-0000000000000" \
  -H 'Idempotency-Key: reserva-ES123' -H 'Content-Type: application/json' \
  -d "{\"building_id\": \"$EDIFICIO\", \"size\": \"M\", \"tracking_ref\": \"ES123\", \"recipient\": \"vecino@example.com\"}"
# {"id":"...","status":"PENDING","building_id":"01a10b7b-...","locker_label":"M-01","size":"M","carrier":"SEUR",
#  "tracking_ref":"ES123","recipient":"vecino@example.com","deposited_at":null,"picked_up_at":null}

# Repetir la misma petición con la misma clave (por ejemplo, porque no llegó la respuesta): 201 con la misma
# entrega, sin reservar otra taquilla
# Misma clave con otro cuerpo: {"code":"IDEMPOTENCY_KEY_REUSED","detail":"La clave ya se usó con otra petición distinta"}
# Otra clave para el mismo paquete: {"code":"DUPLICATE_PACKAGE","detail":"Este paquete ya tiene una reserva activa"}

ENTREGA=01a10b7c-0d3e-7f21-9a4b-5c6d7e8f9a0b   # el id de la entrega que ha devuelto

# SEUR deposita el paquete: 200 con la entrega en DEPOSITED. Repetirlo da 200 con la misma entrega
curl -s -X POST localhost:8000/v1/deliveries/$ENTREGA/deposit -H "X-API-Key: dev-seur-key-0000000000000"
# {"id":"...","status":"DEPOSITED",...,"deposited_at":"2026-10-05T17:20:31.512345Z","picked_up_at":null}

# SEUR consulta su entrega (Correos Express recibiría 404: no es suya)
curl -s localhost:8000/v1/deliveries/$ENTREGA -H "X-API-Key: dev-seur-key-0000000000000"

# El código de recogida no se guarda ni sale en ninguna respuesta: se calcula con el secreto. Con `make worker` en
# marcha, el aviso sale en el log del worker, en una línea JSON con su event_id:
# {"ts":"...","level":"INFO","logger":"locker.notifier","message":"Tu paquete está en la taquilla M-01 del edificio
#  Edificio Sol. Tu código de recogida es 483920.","request_id":null,"event_id":"...","delivery_id":"..."}
# También se puede calcular en una consola
CODIGO=$(uv run python -c "import uuid; from locker.core.config import get_settings; from locker.deliveries.pickup_code import derive; print(derive(get_settings().pickup_code_secret.get_secret_value(), uuid.UUID('$ENTREGA')))")

# El residente recoge, sin clave de API: 200 con la entrega en PICKED_UP, y la taquilla vuelve a estar libre
curl -s -X POST localhost:8000/v1/deliveries/$ENTREGA/pickup -H 'Content-Type: application/json' -d "{\"code\": \"$CODIGO\"}"
# Con otro código: {"code":"INVALID_PICKUP_CODE","detail":"Código de recogida incorrecto"}
# Otra vez, ya recogida: {"code":"INVALID_STATE","detail":"La entrega no está en un estado que permita esta operación"}

# Sin clave
curl -s -X POST localhost:8000/v1/buildings -H 'Content-Type: application/json' -d '{"name": "Edificio Sol"}'
# {"code":"UNAUTHENTICATED","detail":"Falta la clave de API o no es válida"}
```

La documentación interactiva está en <http://127.0.0.1:8000/docs> (botón *Authorize* para poner la clave).

## Comandos

Escribe `make` para ver la lista.

| Comando                          | Qué hace                                                                     |
| -------------------------------- | ---------------------------------------------------------------------------- |
| `make up` / `make stop`          | Levanta o apaga el contenedor de PostgreSQL                                  |
| `make down`                      | Elimina el contenedor (los datos se conservan en el volumen)                 |
| `make destroy`                   | Elimina el contenedor **y los datos**                                        |
| `make psql`                      | Abre una consola SQL dentro de la base de datos                              |
| `make migrate` / `make rollback` | Aplica las migraciones pendientes o deshace la última                        |
| `make migration m="mensaje"`     | Genera una migración a partir de los modelos                                 |
| `make run`                       | Arranca la API con recarga automática en el puerto 8000                      |
| `make worker`                    | Arranca el worker, que envía los avisos y caduca reservas (Ctrl-C para pararlo) |
| `make check`                     | Formatea (`ruff format`), pasa el linter (`ruff check`) y los tipos (`mypy`) |
| `make test`                      | Tests unitarios y de integración (necesita Docker)                           |
| `make test-unit`                 | Solo los unitarios (sin Docker)                                              |
| `make test-integration`          | Solo los de integración (PostgreSQL efímero)                                 |
| `make coverage`                  | Tests con informe de cobertura (`htmlcov/index.html`)                        |
| `make e2e`                       | Levanta el sistema en contenedores (dos réplicas y el worker), migra y pasa E2E y smoke |
| `make smoke BASE_URLS=...`       | Smoke contra un sistema ya levantado (direcciones separadas por comas)       |

## Lo transversal (`src/locker/core/`)

| Archivo                 | Responsabilidad                                                                                                       |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `config.py`             | `DatabaseSettings` (lo único que necesita Alembic) y `Settings` (la API y el worker), y `get_settings`                |
| `database.py`           | Engine, fábrica de sesiones, `Base` de las tablas con su convención de nombres, y `get_session` (una sesión por petición) |
| `exceptions.py`         | `DomainError` y sus familias, con el `code` del catálogo de errores. No saben nada de HTTP                            |
| `exception_handlers.py` | El único sitio que traduce un error a HTTP, siempre con la forma `{"code", "detail"}`                                 |
| `security.py`           | `Principal`, `get_principal` (clave de API → quién llama) y `require_role` (comprueba el rol). No toca la base de datos |
| `middleware.py`         | Genera un identificador (UUID v7) por petición y lo devuelve en `X-Request-ID`                                        |
| `logging.py`            | Formateador JSON y `configure_logging`                                                                                |

`main.py` crea la app: el lifespan lee la configuración, configura los logs y crea el pool de conexiones; registra los manejadores de errores, el middleware, `GET /health` y las rutas de los dominios bajo `/v1`.

**Errores.** Toda respuesta de error tiene la forma `{"code": "...", "detail": "..."}`. Cada familia tiene su código HTTP (`NotFoundError` → 404, `ConflictError` → 409, `ForbiddenError` → 403, `UnauthenticatedError` → 401, `UnprocessableError` → 422, `ServiceUnavailableError` → 503) y un error de dominio solo tiene que heredar de la suya. Los errores de validación de FastAPI se convierten en `422 VALIDATION_ERROR` con un `detail` en texto: `campo: mensaje; campo: mensaje`.

**Logs.** Una línea JSON por registro, con `ts` (ISO 8601 en UTC), `level`, `logger`, `message`, `request_id` (nulo fuera de una petición) y los campos que se pasen con `extra={...}`. Las líneas de Uvicorn también salen en JSON.

**Salud.** `GET /health` ejecuta `SELECT 1` con un límite de 2 segundos. Un único endpoint sirve de comprobación de vida y de disponibilidad: si la base de datos no responde, `503 SERVICE_UNAVAILABLE`.

## Dominios

Cada dominio es un paquete de `src/locker/` con los mismos ficheros: `router.py` (HTTP), `schemas.py` (contrato de la API, Pydantic), `dependencies.py` (cableado), `service.py` (lógica y transacción), `repository.py` (consultas, un `Protocol` y su implementación `Sql...Repository`), `models.py` (tablas, SQLAlchemy) y `exceptions.py` (errores de dominio). Los repositorios nunca hacen `commit` ni `rollback`: la transacción la abre el servicio con `async with session.begin():`.

| Operación                                    | Quién                   | Qué hace                                                                 |
| -------------------------------------------- | ----------------------- | ------------------------------------------------------------------------ |
| `POST /v1/buildings`                         | operador                | Crea un edificio (`201 {"id", "name", "country"}`). El nombre no tiene que ser único; `country` es opcional (`ES` por defecto, dos letras mayúsculas) |
| `POST /v1/buildings/{building_id}/lockers`   | operador                | Da de alta de 1 a 100 taquillas de una talla (`S`, `M` o `L`), libres     |
| `GET /v1/buildings/{building_id}/capacity`   | operador, transportista | Total y libres por talla, en orden `S`, `M`, `L`                          |
| `POST /v1/deliveries`                        | transportista           | Reserva una taquilla libre de la talla pedida y crea la entrega en `PENDING`, con un plazo para depositar (`201`). Exige la cabecera `Idempotency-Key` |
| `POST /v1/deliveries/{delivery_id}/deposit`  | transportista dueño     | Pasa la entrega a `DEPOSITED` y apunta el evento del aviso (`200`)        |
| `GET /v1/deliveries/{delivery_id}`           | transportista dueño     | Devuelve la entrega con su estado actual (`200`), `EXPIRED` si caducó     |
| `POST /v1/deliveries/{delivery_id}/pickup`   | sin clave               | Con el código correcto, pasa la entrega a `PICKED_UP` y libera la taquilla (`200`) |

**Etiquetas.** Cada talla lleva su propio contador por edificio: `S-01`, `M-01` y `M-02` conviven, y a partir de 100 salen tres cifras (`M-100`). Para que dos altas simultáneas no calculen la misma etiqueta, el alta bloquea la fila del edificio (`SELECT ... FOR UPDATE`) antes de contar, todo en la misma transacción: la segunda espera a la primera y sigue la numeración. Además, `uq_lockers_building_id_label` impide etiquetas repetidas en un edificio.

**Capacidad.** Una sola consulta agrupada por talla, con `count(*)` para el total y `count(*) FILTER (WHERE status = 'FREE')` para las libres. Un edificio sin taquillas devuelve `"sizes": []`; uno que no existe, `404 NOT_FOUND`.

**Reservar.** Cuerpo `{"building_id", "size", "tracking_ref", "recipient"}` (sin campos extra) y cabecera `Idempotency-Key` obligatoria (de 1 a 255 caracteres); el transportista es el de la clave de API. En una transacción, y en este orden:

1. **Huella** del cuerpo: SHA-256 en hexadecimal del JSON con las claves ordenadas y sin espacios (`idempotency/fingerprint.py`). El orden de los campos no la cambia.
2. **Registra la clave** con `INSERT ... ON CONFLICT (carrier, key) DO NOTHING RETURNING`. Si no inserta nada, la clave ya existía: con otra huella, `422 IDEMPOTENCY_KEY_REUSED`; con la misma, se devuelve la respuesta guardada, sin tocar nada más. No se mira antes con un `SELECT`: una petición idéntica todavía en curso no se vería. El `INSERT`, en cambio, espera a que esa otra transacción termine, así que la segunda petición recibe la respuesta de la primera.
3. Si el edificio no existe, `404 NOT_FOUND`.
4. **Asigna la taquilla en una sola sentencia**: un `UPDATE ... RETURNING` sobre un CTE que elige la taquilla libre más antigua de esa talla con `FOR UPDATE SKIP LOCKED`. Nunca un `SELECT` y luego un `UPDATE`: entre los dos, otra reserva podría quedarse con la misma taquilla. `SKIP LOCKED` hace que una reserva simultánea salte la taquilla que otra tiene bloqueada en vez de esperarla. Solo la talla exacta: si no queda ninguna libre, `409 NO_LOCKER_AVAILABLE`, aunque haya libres de otra talla.
5. Crea la entrega, con su plazo: `expires_at = now() + RESERVATION_TTL_SECONDS`, calculado por la base de datos. No se mira antes si el paquete ya tiene una reserva: lo impide el índice único parcial `uq_deliveries_active_package`, y el repositorio traduce su error (SQLSTATE `23505` y el nombre del índice) a `409 DUPLICATE_PACKAGE`. El error deshace la transacción entera, así que la taquilla vuelve a quedar libre.
6. **Guarda la respuesta** serializada en la clave. Es lo que recibe un reintento, aunque la entrega haya cambiado de estado después.

Cualquier error deshace también la clave: ninguna reserva fallida la deja guardada, y se puede reintentar con la misma. Las claves son por transportista (la PK es `(carrier, key)`) y no caducan (limitación aceptada A2). Las dos capas protegen cosas distintas: la clave devuelve **la misma respuesta** a la misma petición repetida; el índice `uq_deliveries_active_package` **rechaza** una petición nueva sobre un paquete ya reservado.

Como la taquilla se asigna antes de crear la entrega, un paquete duplicado sin taquillas libres recibe `NO_LOCKER_AVAILABLE` (limitación aceptada A10).

**Ciclo de la entrega.** Cada cambio de estado es un `UPDATE ... WHERE status = <origen>` que mira cuántas filas ha cambiado; nunca se lee el estado en Python para decidir si se puede cambiar. Si dos peticiones cambian la misma entrega a la vez, la segunda espera al bloqueo de la fila, PostgreSQL vuelve a evaluar la condición con la fila ya confirmada y su `UPDATE` no cambia nada.

```
Entrega:   PENDING ──depositar──▶ DEPOSITED ──recoger──▶ PICKED_UP
           PENDING ──caducar────▶ EXPIRED
Taquilla:  FREE ──reservar──▶ BUSY ──recoger o caducar──▶ FREE
```

**Depositar.** Sin cuerpo. `UPDATE deliveries SET status = 'DEPOSITED', deposited_at = now() WHERE id = :id AND carrier = :carrier AND status = 'PENDING'`: solo el transportista dueño y solo desde `PENDING`. Si cambia la fila, en la **misma transacción** se inserta el evento `delivery.deposited` en `outbox_events` (no puede haber un depósito sin evento ni un evento sin depósito) y responde `200`. Si no cambia ninguna, se lee la entrega del mismo transportista para saber por qué: no existe o es de otro → `404 NOT_FOUND` (un `403` revelaría que existe); ya está `DEPOSITED` → `200` con la entrega tal cual y **sin segundo evento** (un transportista que reintenta); cualquier otro estado (`PICKED_UP` o `EXPIRED`) → `409 INVALID_STATE`.

**Consultar.** Una lectura simple, sin transacción. El transportista va en la propia consulta, así que una entrega ajena no se encuentra, igual que una inexistente: `404 NOT_FOUND`.

**Recoger.** Cuerpo `{"code": "483920"}`: exactamente seis cifras del 0 al 9 (`^[0-9]{6}$`; `\d` aceptaría cifras de otros alfabetos), si no `422`. Sin clave de API. En una transacción, y en este orden: la entrega no existe → `404`; no está `DEPOSITED` (sin depositar, ya recogida o caducada) → `409 INVALID_STATE`; el código no es el suyo → `403 INVALID_PICKUP_CODE`, con un `detail` fijo que no repite el código, y nada cambia; `UPDATE ... SET status = 'PICKED_UP', picked_up_at = now() WHERE id = :id AND status = 'DEPOSITED'`, y si otra recogida simultánea ganó y no cambia ninguna fila → `409 INVALID_STATE`; por último libera la taquilla con `UPDATE lockers SET status = 'FREE' WHERE id = :locker_id AND status = 'BUSY'`. Recoger dos veces da `409`, mientras que depositar dos veces da `200` (limitación aceptada A14).

**Código de recogida** (`deliveries/pickup_code.py`). No se guarda: se deriva del secreto y del id de la entrega. `derive` calcula el HMAC-SHA256 del id con `PICKUP_CODE_SECRET` como clave, toma sus cuatro primeros bytes como entero, lo reduce módulo 1.000.000 y lo escribe con ceros a la izquierda hasta seis cifras. `matches` compara en tiempo constante (`hmac.compare_digest`). El código no aparece en ninguna tabla, respuesta, evento ni log. Cambiar el secreto invalida los códigos pendientes, y no hay límite de intentos (limitación aceptada A1).

**Outbox** (`outbox/`). El depósito apunta el evento en la misma transacción (outbox transaccional): `events.py` define el tipo `delivery.deposited` y su contenido, que es solo `{"delivery_id": "..."}`, ni el código ni los datos del residente. Cada evento se crea con `attempts = 0` y `next_attempt_at = now()`. No hay broker: la cola es la propia tabla.

**Worker** (`outbox/worker.py`; conserva el nombre aunque desde F6 también caduca reservas). Un proceso aparte con el mismo código y la misma imagen: `make worker` en local (`python -m locker.outbox.worker`) o el servicio `worker` de Compose. Lee la misma configuración que la API, configura los logs en JSON y crea su propio pool de conexiones. En cada vuelta hace dos tareas: llama a `process_next()` (envía un aviso) y a `expire_next()` (caduca una reserva vencida). Si alguna tenía trabajo, vuelve a empezar sin esperar; si ninguna lo tenía, hace una pausa de `OUTBOX_POLL_INTERVAL_SECONDS`. Cada tarea va en su propio `try`: un error inesperado en una (la base de datos no responde, el esquema aún no está migrado) se registra en el log y no impide la otra, y se reintenta en la siguiente vuelta: el worker no muere. Se para con Ctrl-C (`SIGINT`) o `SIGTERM` (`docker compose stop worker`): termina el evento en curso y sale con código 0 en el momento, aunque esté en mitad de la pausa, porque la pausa espera al evento de parada con un plazo en vez de dormir. Se pueden lanzar varios workers a la vez.

**`process_next`** (`outbox/service.py`). Todo en una transacción, por evento:

1. Toma el evento vencido más antiguo con `SELECT ... WHERE next_attempt_at <= now() ORDER BY next_attempt_at, id LIMIT 1 FOR UPDATE SKIP LOCKED`. El bloqueo impide que dos workers envíen el mismo evento; `SKIP LOCKED` hace que un worker salte el evento que otro tiene bloqueado en vez de esperarlo. Un `next_attempt_at` futuro (esperando a reintentarse) o nulo (muerto) no se toma. Si no hay ninguno, devuelve `False`.
2. Construye el aviso: lee el destinatario, la taquilla y el edificio de la entrega, y calcula el código con `pickup_code.derive`.
3. Lo envía con el notificador y, si sale bien, **borra** el evento.
4. Si algo falla al construir o enviar el aviso (por ejemplo, la entrega no existe o el notificador lanza un error), lo registra en el log con el id del evento y el error (nunca el aviso) y apunta el fallo **sin relanzar el error**, para que la transacción confirme: `attempts + 1` y `next_attempt_at = now() + espera`, con una espera de `OUTBOX_BACKOFF_BASE_SECONDS × 2^(attempts − 1)` (2, 4, 8 y 16 s: el evento aguanta una caída de unos 30 s, limitación aceptada A11). Al llegar a `OUTBOX_MAX_ATTEMPTS`, `next_attempt_at` queda nulo: el evento muere. Si se relanzara el error, la transacción se desharía y el fallo no quedaría apuntado: se reintentaría sin fin y sin espera.

La transacción sigue abierta mientras se envía el aviso (limitación aceptada A3). La entrega es **al menos una vez**: si el aviso sale y algo falla antes de borrar el evento, se reenvía con el mismo `event_id`, para que el receptor reconozca el repetido.

**Notificador** (`outbox/notifier.py`). `Notification` lleva `event_id`, `delivery_id`, `recipient`, `building_name`, `locker_label`, `pickup_code` y `message`; el código y el texto (que lo contiene) no salen en su `repr`. `Notifier` es un `Protocol` con `send`. La única implementación es `LogNotifier`, que escribe el aviso en el logger `locker.notifier`, con `event_id` y `delivery_id` como campos. Es la única línea de log del sistema que lleva el código de recogida (limitación aceptada A5: solo vale para una demostración).

**Eventos muertos.** Un evento que agota sus intentos de envío (`OUTBOX_MAX_ATTEMPTS`) se queda en `outbox_events` con `next_attempt_at` nulo: no avisa a nadie y no se vuelve a tomar (limitación aceptada A4). Cuando se haya arreglado la causa, se reactivan todos con este `UPDATE` (por ejemplo, desde `make psql`), que les devuelve los intentos y los deja vencidos para la siguiente pasada:

```sql
UPDATE outbox_events SET attempts = 0, next_attempt_at = now() WHERE next_attempt_at IS NULL;
```

**Caducidad de reservas** (`deliveries/expiration.py`). Una reserva que no se deposita antes de su plazo (`RESERVATION_TTL_SECONDS`, 30 minutos por defecto) caduca: la entrega pasa a `EXPIRED` y su taquilla vuelve a `FREE`, así que la capacidad la cuenta como libre y el paquete y la taquilla se pueden reservar otra vez. El transportista no conoce el plazo (`expires_at` no sale en ninguna respuesta): descubre la caducidad al consultar su entrega y verla en `EXPIRED`; depositarla o recogerla da `409 INVALID_STATE`, y repetir la reserva con la misma `Idempotency-Key` devuelve la respuesta original (en `PENDING`). Caducar no avisa a nadie: solo deja una línea de log con el `delivery_id`. `ExpirationService.expire_next()` lo hace en una transacción corta por reserva:

1. Toma y caduca la reserva vencida más antigua en **una sola sentencia**: un `UPDATE deliveries SET status = 'EXPIRED' ... WHERE status = 'PENDING' RETURNING id, locker_id` sobre un CTE que la elige con `WHERE status = 'PENDING' AND expires_at <= now() ... FOR UPDATE SKIP LOCKED`. Si no hay ninguna, devuelve `False`.
2. Libera su taquilla con el mismo `UPDATE lockers ... WHERE status = 'BUSY'` que recoger, en la misma transacción: nunca queda una entrega `EXPIRED` con la taquilla ocupada. Si la taquilla no estaba ocupada, el error deshace también la caducidad.

Depositar y caducar compiten por el mismo estado de origen (`PENDING`) y gana uno: si el depósito va primero, la caducidad salta la fila bloqueada y después ya no la ve `PENDING`; si la caducidad va primero, el depósito espera, vuelve a evaluar su condición y responde `409`. Dos workers no caducan la misma reserva: `SKIP LOCKED` hace que cada uno tome una distinta.

**Tablas.** `buildings` (`id`, `name`, `country`), `lockers` (`id`, `building_id`, `label`, `size`, `status`), `deliveries` (`id`, `locker_id`, `carrier`, `tracking_ref`, `recipient`, `status`, `deposited_at`, `picked_up_at`, `expires_at`), `idempotency_keys` (`carrier`, `key`, `request_hash`, `response_body` en JSONB) y `outbox_events` (`id`, que es el `event_id`, `type`, `payload` en JSONB, `attempts` y `next_attempt_at`, donde `NULL` significa evento muerto; sin índices, porque los eventos enviados se borran). Llevan `CHECK` sobre las tallas, los estados y el formato del país, un índice **parcial** `ix_lockers_free_by_size` sobre `(building_id, size)` que solo contiene las taquillas libres, y dos índices **únicos parciales** sobre las entregas activas (`PENDING` o `DEPOSITED`): `uq_deliveries_active_locker` (una taquilla, una entrega activa) y `uq_deliveries_active_package` (un paquete, una entrega activa). Una entrega recogida o caducada no cuenta, así que la taquilla y la referencia se pueden volver a usar. Desde F6, `ck_deliveries_pending_has_expiry` exige plazo a toda reserva `PENDING`, y el índice parcial `ix_deliveries_pending_expiry` sobre `expires_at` (solo las `PENDING`) sostiene la búsqueda de reservas vencidas. Los identificadores son UUID v7 generados por la aplicación.

**Migración con datos.** `country` se añadió a `buildings` cuando ya había edificios, con el patrón expand → backfill → contract en una sola migración: se añade la columna admitiendo `NULL` (expand), se rellena con `UPDATE buildings SET country = 'ES'` (backfill) y después se exige con `NOT NULL` y `ck_buildings_country_format` (contract). Añadirla directamente como `NOT NULL` fallaría con los edificios existentes. El `downgrade` quita el `CHECK` y la columna, y conserva los edificios. La caducidad (F6) siguió el mismo patrón en `deliveries`: `expires_at` admitiendo `NULL`, las reservas `PENDING` que ya había reciben 30 minutos desde la migración, y después el `CHECK` de estados admite `EXPIRED` y llegan el `CHECK` del plazo y el índice. Su `downgrade` pasa las entregas `EXPIRED` a `PICKED_UP` (pérdida asumida: el `CHECK` antiguo no admite `EXPIRED`, y en `PENDING` volverían a ocupar la taquilla).

## Docker

La misma imagen (`Dockerfile`) arranca la API, el worker y aplica las migraciones; solo cambia el comando. En `compose.yml`:

| Servicio  | Qué es                                                                                    |
| --------- | ----------------------------------------------------------------------------------------- |
| `db`      | PostgreSQL 18 en el puerto 5432, con healthcheck `pg_isready`                             |
| `migrate` | Perfil `app`. Ejecuta `alembic upgrade head` y termina                                    |
| `api-1`   | Perfil `app`. La API en el puerto 8001, con healthcheck contra `/health`                  |
| `api-2`   | Perfil `app`. La misma API en el puerto 8002                                              |
| `worker`  | Perfil `app`. El worker (`python -m locker.outbox.worker`): envía los avisos y caduca reservas, con las mismas variables que las APIs |

El perfil `app` hace que `make up` levante solo PostgreSQL para el día a día. Las migraciones nunca se aplican al arrancar la API: son un paso explícito, como en un pipeline de despliegue.

## Tests

Tres niveles; cada comportamiento se prueba en el más bajo que caza su bug:

| Nivel       | Carpeta             | Qué prueba                                                                                          |
| ----------- | ------------------- | --------------------------------------------------------------------------------------------------- |
| Unitario    | `tests/unit`        | Lógica pura en memoria: traducción de errores, formateador de logs, validación de `API_KEYS` y de `RESERVATION_TTL_SECONDS`, etiquetas, huella, código de recogida, espera y agotamiento de los reintentos |
| Integración | `tests/integration` | La API en el mismo proceso (httpx + `ASGITransport`), el servicio del outbox, la caducidad y el bucle del worker, contra PostgreSQL real |
| E2E y smoke | `tests/e2e`         | Peticiones reales contra el sistema en contenedores, en cada réplica, y el worker desplegado        |

- **PostgreSQL real y efímero** ([testcontainers](https://testcontainers-python.readthedocs.io/), imagen `postgres:18`, la misma que `compose.yml`). Nunca se toca la base de datos de desarrollo.
- **Esquema con Alembic**: `alembic upgrade head` en un subproceso, como `make migrate`, desde un directorio vacío para que no lea ningún `.env`.
- **Aislamiento**: al terminar cada test se vacían las tablas con `TRUNCATE ... RESTART IDENTITY CASCADE`.
- **Una sesión por petición**, como en producción, sustituyendo `get_session` con `dependency_overrides`.
- **Configuración propia**: los tests sustituyen `get_settings` con claves de prueba, así que no dependen del `.env` ni de `API_KEYS` del entorno.
- **Concurrencia** con varias sesiones y `asyncio.gather` (dos altas de taquillas a la vez, 10 reservas para 5 taquillas, dos reservas idénticas con la misma clave, dos recogidas de la misma entrega), sin `sleep`. Los casos deterministas dejan una transacción abierta (con el edificio bloqueado, una taquilla ocupada, una clave registrada, una entrega depositada o recogida) y esperan a ver la petición parada en un bloqueo en `pg_stat_activity`. Antes de lanzarlas se abren las conexiones del pool: si no, las peticiones no llegan a solaparse y el test pasaría aunque faltase la protección. Entre procesos reales, un E2E reparte 10 reservas entre `api-1` y `api-2` con hilos.
- **Migraciones**: un test comprueba que `alembic check` no ve diferencias y que todas las migraciones bajan y suben en una base de datos vacía. Otro migra hasta la revisión anterior a `country`, inserta edificios, aplica la de `country` y comprueba que se conservan con `ES`, también tras bajar y volver a subir. Y otro hace lo mismo con la caducidad: entregas en cada estado, plazo solo para las `PENDING`, el `CHECK` nuevo, y un `downgrade` que pasa las `EXPIRED` a `PICKED_UP`.
- **Sin dobles**, salvo uno: la base de datos caída se prueba con una URL inalcanzable, y la atomicidad del depósito con un trigger que hace fallar de verdad el `INSERT` del evento (la entrega sigue `PENDING`). La única excepción es `NotificadorFalso` (`tests/integration/notificador_falso.py`), porque un fallo del sistema que envía el aviso no se puede provocar de verdad: graba cada aviso y falla cuando se le pide, antes o después de grabarlo.
- **El worker**: los tests de `process_next` cubren el envío (con el código calculado por el test), la cola vacía, el evento no vencido, el fallo (que confirma y programa el reintento), cinco fallos hasta el evento muerto, su reactivación con el `UPDATE` del README, el reenvío con el mismo `event_id` y el evento sin entrega. Los reintentos no esperan: la base de la espera es 0 en los tests. Dos workers a la vez envían cada evento una sola vez, y un caso determinista deja un evento bloqueado por otra transacción y comprueba que se salta sin esperar. El bucle se prueba sin señales ni procesos: se para al instante aunque la pausa sea de 60 s, y sobrevive a una base de datos sin migrar hasta que se migra. Con un aviso pendiente y una reserva vencida, hace las dos cosas en el mismo bucle, y un trigger que rompe una de las dos tareas no impide la otra.
- **La caducidad**: el plazo se adelanta escribiendo `expires_at` en la fila, sin esperar. Los tests cubren qué caduca y qué no (ni una `PENDING` en plazo, ni una `DEPOSITED` o `PICKED_UP` con el plazo pasado), que la taquilla y el paquete se pueden reservar otra vez, y que una caducada se consulta como `EXPIRED` y da `409` al depositar o recoger. La carrera con depositar se repite varias veces y tiene dos casos deterministas (cada uno fuerza un ganador), y dos workers a la vez caducan cada reserva una sola vez. Un E2E adelanta el plazo de una reserva y espera, como mucho 10 s, a que el worker desplegado la caduque.
- **El código de recogida**: los tests lo calculan con `pickup_code.derive` y el secreto de su configuración, y comprueban que no aparece en ninguna respuesta del ciclo ni en los logs. El E2E recorre reservar, depositar y recoger alternando `api-1` y `api-2`, con el secreto del `.env`. Otro E2E deposita y espera, como mucho 10 s, a que el worker desplegado envíe el aviso y borre el evento de esa entrega.

`make test` no ejecuta los E2E. `make e2e` levanta `db`, aplica las migraciones con `migrate`, arranca `api-1`, `api-2` y `worker` y pasa `tests/e2e` contra `http://127.0.0.1:8001` y `http://127.0.0.1:8002`; al terminar los para. Usa la base de datos de desarrollo.

Se sigue TDD: el test en rojo se sube marcado con `@pytest.mark.xfail(strict=True)` y el commit que lo arregla quita el marcador.

## CI y CD

GitHub Actions (`.github/workflows/ci.yml`) ejecuta en cada push a `main` y en cada pull request: `uv sync --locked`, `make check`, `git diff --exit-code` (como `make check` formatea en vez de fallar, comprueba que el código ya venía formateado) y `make test`. No ejecuta E2E ni smoke.

El CD (`.github/workflows/cd.yml`) despliega en Google Cloud. **No** corre en cada push a `main`: cada despliegue gasta presupuesto, así que se lanza a mano (pestaña *Actions*, `workflow_dispatch`) o subiendo una etiqueta `v*`. Tiene dos trabajos: `verify` repite los pasos del CI, y `deploy` (que solo empieza si `verify` pasa) construye la imagen, migra, despliega la API y el worker y pasa el smoke contra la URL pública. Detalles en la sección siguiente.

## Despliegue en Google Cloud

Un despliegue **efímero y de demostración** (no es producción): se enciende para una prueba o una entrevista y se borra. Las decisiones están en [`docs/especificaciones.md`](docs/especificaciones.md) §13.5.

| Pieza                    | Qué es                                                                                         |
| ------------------------ | ---------------------------------------------------------------------------------------------- |
| `locker-api`             | Servicio de Cloud Run: la API, pública y con HTTPS, de 0 a 2 instancias (1 vCPU, 512 MiB)       |
| `locker-worker`          | *Worker pool* de Cloud Run: el worker, 1 instancia siempre encendida (1 vCPU, 512 MiB)          |
| `locker-migrate`         | *Job* de Cloud Run: `alembic upgrade head`, que el CD ejecuta antes de desplegar                |
| `locker-db`              | Cloud SQL, PostgreSQL 18, `db-f1-micro`, 10 GB SSD, sin alta disponibilidad. Se llega por el socket de Cloud SQL, sin redes autorizadas |
| `locker`                 | Repositorio Docker de Artifact Registry; cada imagen se etiqueta con el SHA del commit          |
| Secret Manager           | `locker-api-keys` (`API_KEYS`), `locker-pickup-secret` (`PICKUP_CODE_SECRET`) y `locker-db-url` (`DATABASE_URL`) |
| `locker-runtime`         | Cuenta de servicio con la que corren los contenedores: solo lee secretos y se conecta a Cloud SQL |
| `locker-deployer`        | Cuenta de servicio con la que despliega GitHub Actions, por federación de identidad (sin claves) |

Todo vive en el proyecto `locker-api-cristian`, región `europe-west1`. La misma imagen del `Dockerfile` arranca la API, el worker y las migraciones; los contenedores reciben los secretos de Secret Manager como variables de entorno al arrancar, así que nunca pasan por GitHub.

### Preparación (una vez por despliegue)

Necesitas `gcloud` con una configuración `locker-api` activa que apunte al proyecto (`gcloud config configurations activate locker-api`), `gh` con sesión iniciada, y el proyecto con una cuenta de facturación **vinculada** (los scripts no la vinculan: lo decides tú).

```bash
gcloud billing projects link locker-api-cristian --billing-account=<id de tu cuenta>   # empieza a facturar
deploy/setup.sh                  # APIs, Artifact Registry, Cloud SQL (tarda unos minutos), secretos, permisos y presupuesto
```

`setup.sh` es **idempotente**: comprueba cada recurso antes de crearlo, así que se puede repetir sin duplicar nada ni cambiar las claves. Genera las claves de API, el secreto del código de recogida y la contraseña de la base de datos con `openssl rand` y los guarda directamente en Secret Manager: no los imprime ni los escribe en ningún fichero. Al terminar imprime las cuatro **variables** del repositorio de GitHub (no son secretos) y los comandos `gh variable set` para crearlas: `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER` y `GCP_DEPLOYER_SA`.

Para desplegar, sube una etiqueta (o, cuando el workflow esté en `main`, lánzalo desde la pestaña *Actions*):

```bash
git tag v0.1.0-gcp1 && git push origin v0.1.0-gcp1
gh run watch                     # sigue la ejecución
gcloud run services describe locker-api --project=locker-api-cristian --region=europe-west1 --format='value(status.url)'
```

Para probar a mano, las claves se leen de Secret Manager (no las pegues en ningún sitio):

```bash
gcloud secrets versions access latest --secret=locker-api-keys --project=locker-api-cristian
```

El aviso al residente (con el código de recogida, A5) sale en el log del worker, en Cloud Logging:

```bash
gcloud logging read 'jsonPayload.logger="locker.notifier"' --project=locker-api-cristian --limit=5
```

**gcloud de Homebrew en macOS.** Desplegar, cambiar o borrar un *worker pool* necesita el módulo `grpc` en el Python que usa `gcloud`. El cask de Homebrew no trae el Python propio del SDK, y si `gcloud` acaba usando otro sin `grpc`, `gcloud run worker-pools delete` no carga (`teardown.sh` lo comprueba antes de borrar nada). Solución: un Python aparte con `grpcio` solo para `gcloud`:

```bash
uv venv ~/.gcloud-python --python 3.13 && uv pip install --python ~/.gcloud-python/bin/python grpcio
export CLOUDSDK_PYTHON=~/.gcloud-python/bin/python CLOUDSDK_PYTHON_SITEPACKAGES=1
```

En GitHub Actions no hace falta: el SDK que instala `setup-gcloud` trae su propio Python con `grpc`.

### Coste

Precios aproximados de `europe-west1`, en orden de magnitud (la referencia es la calculadora de Google Cloud):

| Pieza                                 | Coste aproximado                                    |
| ------------------------------------- | --------------------------------------------------- |
| Worker pool (1 vCPU, siempre encendido) | ~1,5 € al día: es lo que más gasta                 |
| Cloud SQL `db-f1-micro`               | ~0,3 € al día, más ~0,06 € al día por los 10 GB de disco |
| API (Cloud Run, de 0 a 2 instancias)  | ~0 €: sin tráfico no hay instancias, y las pruebas caben en la capa gratuita |
| Artifact Registry, Secret Manager, federación, cuentas de servicio | ~0 € (capa gratuita o sin coste)       |
| GitHub Actions                        | 0 € (repositorio público)                           |

Con todo encendido, unos **2 € al día**. El tope del despliegue es **5 €**: `setup.sh` crea un presupuesto de 5 EUR que avisa por correo al 50, 90 y 100 %. Un presupuesto avisa, **no corta** el gasto: lo que lo corta es apagar o borrar.

### Apagar sin borrar

Solo Cloud SQL y el worker pool facturan sin parar; la API escala a 0 sola.

```bash
# Apagar: el worker a 0 instancias y Cloud SQL parada (se sigue pagando el disco)
gcloud run worker-pools update locker-worker --instances=0 --project=locker-api-cristian --region=europe-west1
gcloud sql instances patch locker-db --activation-policy=never --project=locker-api-cristian

# Encender otra vez
gcloud sql instances patch locker-db --activation-policy=always --project=locker-api-cristian
gcloud run worker-pools update locker-worker --instances=1 --project=locker-api-cristian --region=europe-west1
```

### Borrarlo todo

```bash
deploy/teardown.sh --unlink-billing
```

Borra Cloud SQL (con sus datos), el servicio, el worker pool, el job y los secretos, y con `--unlink-billing` desvincula la facturación: sin cuenta vinculada, el proyecto ya no puede facturar nada. Antes de borrar comprueba que todo lo que va a borrar es de este despliegue; si aparece algo más, para sin tocar nada. Quedan, sin coste, el repositorio de imágenes, las cuentas de servicio, la federación, el presupuesto y las APIs activadas, que `setup.sh` reutiliza. No borra el proyecto. Ojo: Cloud SQL no deja reutilizar el nombre `locker-db` hasta una semana después de borrar la instancia, así que un `setup.sh` justo después de un `teardown.sh` falla al crearla.

### Limitaciones del despliegue

- Es de demostración (A9), con la instancia de Cloud SQL más barata: sin alta disponibilidad ni SLA (A26).
- La API es pública y solo la protegen las claves de API. Como no hay límite de intentos al recoger (A1), el código de recogida es adivinable por fuerza bruta si se conoce el `id` de la entrega, un UUID (A27).
- La infraestructura se prepara con scripts de bash, no de forma declarativa: no detectan cambios hechos a mano en la consola (A28).
- Las claves no se rotan: hacerlo exige volver a ejecutar el script (tras borrar el secreto) y redesplegar (A29).
