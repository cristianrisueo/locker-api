# Locker API

API de taquillas para paquetería: un transportista reserva una taquilla de un edificio, deposita el paquete y el residente lo recoge con un código. Python 3.14, FastAPI y PostgreSQL.

Qué hace el sistema y cómo se construye está en [`docs/especificaciones.md`](docs/especificaciones.md); el orden de construcción, por fases, en [`docs/plan_fases.md`](docs/plan_fases.md).

> **Estado: F3.** Sobre la base de F0 (errores, logs, identificador de petición, `/health`, contenedores con dos réplicas, tests y CI) hay claves de API con roles, alta de edificios (con país), alta de taquillas con etiqueta generada, consulta de capacidad y **reserva de taquilla** segura bajo concurrencia, también entre réplicas, con **`Idempotency-Key` obligatoria**: repetir una reserva devuelve la misma respuesta. `country` se añadió a `buildings` con una **migración con datos**. Todavía no se puede depositar, recoger ni consultar una entrega.

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

Se leen del entorno y, si no están, del `.env`. Si falta una obligatoria, la API no arranca.

### Claves de API

Cada operación de `/v1` exige la cabecera `X-API-Key`. Las claves y sus roles están en `API_KEYS`, una lista de `{"key", "role", "name"}`:

| Rol        | Qué puede hacer                                         | `name`                                                   |
| ---------- | ------------------------------------------------------- | -------------------------------------------------------- |
| `operator` | Crear edificios, dar de alta taquillas, ver capacidad   | No hace falta                                            |
| `carrier`  | Ver capacidad y reservar (en fases siguientes, también depositar) | Obligatorio: es el nombre del transportista (`SEUR`) |

Al arrancar se valida la lista: no puede estar vacía, los roles son `operator` o `carrier`, cada `carrier` lleva `name` y las claves tienen al menos 16 caracteres y no se repiten. Si algo falla, la API no arranca y el error no muestra ninguna clave.

`.env.example` trae tres claves de desarrollo (no son secretos): `dev-operator-key-000000000` (operador), `dev-seur-key-0000000000000` (SEUR) y `dev-correos-key-00000000000` (Correos Express).

Sin clave, o con una que no existe, la respuesta es `401 UNAUTHENTICATED`; con una clave válida de un rol sin permiso, `403 FORBIDDEN`. La clave se compara con todas las configuradas en tiempo constante (`hmac.compare_digest`) y nunca aparece en logs ni respuestas.

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
| `make check`                     | Formatea (`ruff format`), pasa el linter (`ruff check`) y los tipos (`mypy`) |
| `make test`                      | Tests unitarios y de integración (necesita Docker)                           |
| `make test-unit`                 | Solo los unitarios (sin Docker)                                              |
| `make test-integration`          | Solo los de integración (PostgreSQL efímero)                                 |
| `make coverage`                  | Tests con informe de cobertura (`htmlcov/index.html`)                        |
| `make e2e`                       | Levanta el sistema en contenedores, migra y pasa E2E y smoke                 |
| `make smoke BASE_URLS=...`       | Smoke contra un sistema ya levantado (direcciones separadas por comas)       |

## Lo transversal (`src/locker/core/`)

| Archivo                 | Responsabilidad                                                                                                       |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `config.py`             | `DatabaseSettings` (lo único que necesita Alembic) y `Settings` (la API), y `get_settings`                            |
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
| `POST /v1/deliveries`                        | transportista           | Reserva una taquilla libre de la talla pedida y crea la entrega en `PENDING` (`201`). Exige la cabecera `Idempotency-Key` |

**Etiquetas.** Cada talla lleva su propio contador por edificio: `S-01`, `M-01` y `M-02` conviven, y a partir de 100 salen tres cifras (`M-100`). Para que dos altas simultáneas no calculen la misma etiqueta, el alta bloquea la fila del edificio (`SELECT ... FOR UPDATE`) antes de contar, todo en la misma transacción: la segunda espera a la primera y sigue la numeración. Además, `uq_lockers_building_id_label` impide etiquetas repetidas en un edificio.

**Capacidad.** Una sola consulta agrupada por talla, con `count(*)` para el total y `count(*) FILTER (WHERE status = 'FREE')` para las libres. Un edificio sin taquillas devuelve `"sizes": []`; uno que no existe, `404 NOT_FOUND`.

**Reservar.** Cuerpo `{"building_id", "size", "tracking_ref", "recipient"}` (sin campos extra) y cabecera `Idempotency-Key` obligatoria (de 1 a 255 caracteres); el transportista es el de la clave de API. En una transacción, y en este orden:

1. **Huella** del cuerpo: SHA-256 en hexadecimal del JSON con las claves ordenadas y sin espacios (`idempotency/fingerprint.py`). El orden de los campos no la cambia.
2. **Registra la clave** con `INSERT ... ON CONFLICT (carrier, key) DO NOTHING RETURNING`. Si no inserta nada, la clave ya existía: con otra huella, `422 IDEMPOTENCY_KEY_REUSED`; con la misma, se devuelve la respuesta guardada, sin tocar nada más. No se mira antes con un `SELECT`: una petición idéntica todavía en curso no se vería. El `INSERT`, en cambio, espera a que esa otra transacción termine, así que la segunda petición recibe la respuesta de la primera.
3. Si el edificio no existe, `404 NOT_FOUND`.
4. **Asigna la taquilla en una sola sentencia**: un `UPDATE ... RETURNING` sobre un CTE que elige la taquilla libre más antigua de esa talla con `FOR UPDATE SKIP LOCKED`. Nunca un `SELECT` y luego un `UPDATE`: entre los dos, otra reserva podría quedarse con la misma taquilla. `SKIP LOCKED` hace que una reserva simultánea salte la taquilla que otra tiene bloqueada en vez de esperarla. Solo la talla exacta: si no queda ninguna libre, `409 NO_LOCKER_AVAILABLE`, aunque haya libres de otra talla.
5. Crea la entrega. No se mira antes si el paquete ya tiene una reserva: lo impide el índice único parcial `uq_deliveries_active_package`, y el repositorio traduce su error (SQLSTATE `23505` y el nombre del índice) a `409 DUPLICATE_PACKAGE`. El error deshace la transacción entera, así que la taquilla vuelve a quedar libre.
6. **Guarda la respuesta** serializada en la clave. Es lo que recibe un reintento, aunque la entrega haya cambiado de estado después.

Cualquier error deshace también la clave: ninguna reserva fallida la deja guardada, y se puede reintentar con la misma. Las claves son por transportista (la PK es `(carrier, key)`) y no caducan (limitación aceptada A2). Las dos capas protegen cosas distintas: la clave devuelve **la misma respuesta** a la misma petición repetida; el índice `uq_deliveries_active_package` **rechaza** una petición nueva sobre un paquete ya reservado.

Como la taquilla se asigna antes de crear la entrega, un paquete duplicado sin taquillas libres recibe `NO_LOCKER_AVAILABLE` (limitación aceptada A10).

**Tablas.** `buildings` (`id`, `name`, `country`), `lockers` (`id`, `building_id`, `label`, `size`, `status`), `deliveries` (`id`, `locker_id`, `carrier`, `tracking_ref`, `recipient`, `status`, `deposited_at`, `picked_up_at`) e `idempotency_keys` (`carrier`, `key`, `request_hash`, `response_body` en JSONB). Llevan `CHECK` sobre las tallas, los estados y el formato del país, un índice **parcial** `ix_lockers_free_by_size` sobre `(building_id, size)` que solo contiene las taquillas libres, y dos índices **únicos parciales** sobre las entregas activas (`PENDING` o `DEPOSITED`): `uq_deliveries_active_locker` (una taquilla, una entrega activa) y `uq_deliveries_active_package` (un paquete, una entrega activa). Una entrega recogida no cuenta, así que la taquilla y la referencia se pueden volver a usar. Los identificadores son UUID v7 generados por la aplicación.

**Migración con datos.** `country` se añadió a `buildings` cuando ya había edificios, con el patrón expand → backfill → contract en una sola migración: se añade la columna admitiendo `NULL` (expand), se rellena con `UPDATE buildings SET country = 'ES'` (backfill) y después se exige con `NOT NULL` y `ck_buildings_country_format` (contract). Añadirla directamente como `NOT NULL` fallaría con los edificios existentes. El `downgrade` quita el `CHECK` y la columna, y conserva los edificios.

## Docker

La misma imagen (`Dockerfile`) arranca la API y aplica las migraciones; solo cambia el comando. En `compose.yml`:

| Servicio  | Qué es                                                                                    |
| --------- | ----------------------------------------------------------------------------------------- |
| `db`      | PostgreSQL 18 en el puerto 5432, con healthcheck `pg_isready`                             |
| `migrate` | Perfil `app`. Ejecuta `alembic upgrade head` y termina                                    |
| `api-1`   | Perfil `app`. La API en el puerto 8001, con healthcheck contra `/health`                  |
| `api-2`   | Perfil `app`. La misma API en el puerto 8002                                              |

El perfil `app` hace que `make up` levante solo PostgreSQL para el día a día. Las migraciones nunca se aplican al arrancar la API: son un paso explícito, como en un pipeline de despliegue.

## Tests

Tres niveles; cada comportamiento se prueba en el más bajo que caza su bug:

| Nivel       | Carpeta             | Qué prueba                                                                                          |
| ----------- | ------------------- | --------------------------------------------------------------------------------------------------- |
| Unitario    | `tests/unit`        | Lógica pura en memoria: traducción de errores, formateador de logs, validación de `API_KEYS`, etiquetas, huella |
| Integración | `tests/integration` | La API en el mismo proceso (httpx + `ASGITransport`) contra PostgreSQL real                         |
| E2E y smoke | `tests/e2e`         | Peticiones reales contra el sistema en contenedores, en cada réplica                                |

- **PostgreSQL real y efímero** ([testcontainers](https://testcontainers-python.readthedocs.io/), imagen `postgres:18`, la misma que `compose.yml`). Nunca se toca la base de datos de desarrollo.
- **Esquema con Alembic**: `alembic upgrade head` en un subproceso, como `make migrate`, desde un directorio vacío para que no lea ningún `.env`.
- **Aislamiento**: al terminar cada test se vacían las tablas con `TRUNCATE ... RESTART IDENTITY CASCADE`.
- **Una sesión por petición**, como en producción, sustituyendo `get_session` con `dependency_overrides`.
- **Configuración propia**: los tests sustituyen `get_settings` con claves de prueba, así que no dependen del `.env` ni de `API_KEYS` del entorno.
- **Concurrencia** con varias sesiones y `asyncio.gather` (dos altas de taquillas a la vez, 10 reservas para 5 taquillas, dos reservas idénticas con la misma clave), sin `sleep`. Los casos deterministas dejan una transacción abierta (con el edificio bloqueado, una taquilla ocupada o una clave registrada) y esperan a ver la petición parada en un bloqueo en `pg_stat_activity`. Antes de lanzarlas se abren las conexiones del pool: si no, las peticiones no llegan a solaparse y el test pasaría aunque faltase la protección. Entre procesos reales, un E2E reparte 10 reservas entre `api-1` y `api-2` con hilos.
- **Migraciones**: un test comprueba que `alembic check` no ve diferencias y que todas las migraciones bajan y suben en una base de datos vacía. Otro migra hasta la revisión anterior a `country`, inserta edificios, aplica la de `country` y comprueba que se conservan con `ES`, también tras bajar y volver a subir.
- **Sin dobles**: la base de datos caída se prueba con una URL inalcanzable.

`make test` no ejecuta los E2E. `make e2e` levanta `db`, aplica las migraciones con `migrate`, arranca `api-1` y `api-2` y pasa `tests/e2e` contra `http://127.0.0.1:8001` y `http://127.0.0.1:8002`; al terminar para las réplicas. Usa la base de datos de desarrollo.

Se sigue TDD: el test en rojo se sube marcado con `@pytest.mark.xfail(strict=True)` y el commit que lo arregla quita el marcador.

## CI

GitHub Actions (`.github/workflows/ci.yml`) ejecuta en cada push a `main` y en cada pull request: `uv sync --locked`, `make check`, `git diff --exit-code` (como `make check` formatea en vez de fallar, comprueba que el código ya venía formateado) y `make test`. No ejecuta E2E ni smoke.
