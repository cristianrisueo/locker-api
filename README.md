# Locker API

API de taquillas para paquetería: un transportista reserva una taquilla de un edificio, deposita el paquete y el residente lo recoge con un código. Python 3.14, FastAPI y PostgreSQL.

Qué hace el sistema y cómo se construye está en [`docs/especificaciones.md`](docs/especificaciones.md); el orden de construcción, por fases, en [`docs/plan_fases.md`](docs/plan_fases.md).

> **Estado: F0.** Hay entorno, infraestructura transversal (errores, logs, identificador de petición, `/health`), contenedores con dos réplicas, tests y CI. Todavía no hay ningún dominio ni endpoints de negocio.

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
make migrate           # aplica las migraciones (todavía no hay ninguna)
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

Se leen del entorno y, si no están, del `.env`. Si falta una obligatoria, la API no arranca.

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
| `middleware.py`         | Genera un identificador (UUID v7) por petición y lo devuelve en `X-Request-ID`                                        |
| `logging.py`            | Formateador JSON y `configure_logging`                                                                                |

`main.py` crea la app: el lifespan lee la configuración, configura los logs y crea el pool de conexiones; registra los manejadores de errores, el middleware y `GET /health`.

**Errores.** Toda respuesta de error tiene la forma `{"code": "...", "detail": "..."}`. Cada familia tiene su código HTTP (`NotFoundError` → 404, `ConflictError` → 409, `ForbiddenError` → 403, `UnauthenticatedError` → 401, `UnprocessableError` → 422, `ServiceUnavailableError` → 503) y un error de dominio solo tiene que heredar de la suya. Los errores de validación de FastAPI se convierten en `422 VALIDATION_ERROR` con un `detail` en texto: `campo: mensaje; campo: mensaje`.

**Logs.** Una línea JSON por registro, con `ts` (ISO 8601 en UTC), `level`, `logger`, `message`, `request_id` (nulo fuera de una petición) y los campos que se pasen con `extra={...}`. Las líneas de Uvicorn también salen en JSON.

**Salud.** `GET /health` ejecuta `SELECT 1` con un límite de 2 segundos. Un único endpoint sirve de comprobación de vida y de disponibilidad: si la base de datos no responde, `503 SERVICE_UNAVAILABLE`.

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
| Unitario    | `tests/unit`        | Lógica pura en memoria: traducción de errores, formateador de logs                                  |
| Integración | `tests/integration` | La API en el mismo proceso (httpx + `ASGITransport`) contra PostgreSQL real                         |
| E2E y smoke | `tests/e2e`         | Peticiones reales contra el sistema en contenedores, en cada réplica                                |

- **PostgreSQL real y efímero** ([testcontainers](https://testcontainers-python.readthedocs.io/), imagen `postgres:18`, la misma que `compose.yml`). Nunca se toca la base de datos de desarrollo.
- **Esquema con Alembic**: `alembic upgrade head` en un subproceso, como `make migrate`, desde un directorio vacío para que no lea ningún `.env`.
- **Aislamiento**: al terminar cada test se vacían las tablas con `TRUNCATE ... RESTART IDENTITY CASCADE`.
- **Una sesión por petición**, como en producción, sustituyendo `get_session` con `dependency_overrides`.
- **Sin dobles**: la base de datos caída se prueba con una URL inalcanzable.

`make test` no ejecuta los E2E. `make e2e` levanta `db`, aplica las migraciones con `migrate`, arranca `api-1` y `api-2` y pasa `tests/e2e` contra `http://127.0.0.1:8001` y `http://127.0.0.1:8002`; al terminar para las réplicas. Usa la base de datos de desarrollo.

Se sigue TDD: el test en rojo se sube marcado con `@pytest.mark.xfail(strict=True)` y el commit que lo arregla quita el marcador.

## CI

GitHub Actions (`.github/workflows/ci.yml`) ejecuta en cada push a `main` y en cada pull request: `uv sync --locked`, `make check`, `git diff --exit-code` (como `make check` formatea en vez de fallar, comprueba que el código ya venía formateado) y `make test`. No ejecuta E2E ni smoke.
