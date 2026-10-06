# Locker API — Plan de fases

> **Estado: inmutable durante las fases.** Define cómo se construye el proyecto, fase a fase. Qué hace el sistema está en
> [`especificaciones.md`](especificaciones.md) (se cita por sección: «§7.5»); este plan nunca lo contradice. Si algo no
> cuadra, la sesión de Claude Code para y avisa.

## Contenido

1. Cómo se trabaja cada fase
2. Resumen de fases
3. F0 — Entorno y base transversal
4. F1 — Edificios, taquillas y seguridad
5. F2 — Reserva bajo concurrencia
6. F3 — Idempotencia y migración con datos
7. F4 — Depositar, recoger y consultar
8. F5 — Worker y notificador
9. Cierre del núcleo
10. F6 — Caducidad de reservas

---

## 1. Cómo se trabaja cada fase

### 1.1 Flujo

1. **Preparar** (desarrollador). Con `main` limpio y la fase anterior fusionada, abrir una sesión nueva de Claude Code
   en la raíz del repositorio y lanzar el *prompt de arranque* (§1.3) con el número de fase.
2. **Construir** (Claude Code). Crea la rama `fase/F<N>-<nombre>` desde `main` y sigue el orden de commits de la fase:
   esqueletos, tests en rojo con `xfail(strict=True)`, implementación y retirada del `xfail`.
3. **Verificar** (Claude Code). `make check`, `make test` y, si la fase lo pide, `make e2e`. Sube la rama
   (`git push -u origin fase/F<N>-<nombre>`) y entrega el resumen final.
4. **Revisar** (desarrollador y chat de Claude). El desarrollador abre la PR (el CI corre en la PR). La rama se revisa
   en el chat viendo el **diff de la fase** (`git diff main...fase/F<N>-<nombre>`), con el foco puesto en los puntos
   críticos de cada fase. En las partes marcadas como críticas, el desarrollador explica con sus palabras cómo funciona
   antes de fusionar.
5. **Fusionar** (desarrollador). Con la revisión hecha y el CI en verde:

   ```sh
   git switch main && git merge --no-ff fase/F<N>-<nombre> && make test && git branch -d fase/F<N>-<nombre>
   ```

   Si `make test` falla en `main`, se revierte la fusión (`git reset --hard ORIG_HEAD`) y se vuelve al paso 2.
6. **Siguiente fase**, en una sesión nueva. Las fases **no se encadenan**: una por sesión.

El primer commit de `main` lo hace el desarrollador: `CLAUDE.md`, `docs/especificaciones.md` y `docs/plan_fases.md`
(`docs: añadir especificaciones, plan de fases y CLAUDE.md`).

### 1.2 Definición de «hecho» (común a todas las fases)

- **D1.** Cada caso de la fase existe como test, con su identificador al principio del docstring (`«[F2-06] ...»`) para
  poder rastrearlo.
- **D2.** No queda ningún `xfail`, `print`, código comentado ni `TODO`.
- **D3.** `make check` no da errores y no deja cambios sin commit (`git diff --exit-code`).
- **D4.** `make test` pasa completo. Si la fase lo pide, `make e2e` también.
- **D5.** Toda migración nueva tiene `downgrade`, y `alembic check` no detecta diferencias entre modelos y migraciones.
- **D6.** Sin dependencias nuevas respecto a `especificaciones.md` §10, y sin ficheros fuera del alcance de la fase.
- **D7.** El CI de la PR está en verde.
- **D8.** El resumen final dice qué se hizo, qué no y qué dudas o decisiones hubo.

### 1.3 Prompt de arranque

Sustituye `<N>` y `<nombre>`:

```
Lee CLAUDE.md, docs/especificaciones.md y la sección «F<N>» de docs/plan_fases.md (y la §1 de ese plan).
Implementa únicamente la fase F<N> en la rama fase/F<N>-<nombre>, siguiendo el orden de commits del plan.
No empieces otras fases ni modifiques los documentos de docs/. Si algo no cuadra con las especificaciones, para y dímelo.
Al terminar: make check, make test (y make e2e si la fase lo pide), sube la rama y dame el resumen final.
```

### 1.4 Reglas de los tests de las fases

- Los casos están numerados `F<N>-<nn>`. Los nombres de las funciones son libres, en castellano, y empiezan por `test_`.
- Los ficheros de test que se citan son sugeridos; se pueden dividir, pero no mezclar niveles.
- Nivel: **U** unitario, **I** integración, **E** E2E.
- Las fases posteriores no modifican ni borran los tests de las anteriores (pueden añadir tests en los mismos ficheros), salvo lo que el plan indique expresamente.

---

## 2. Resumen de fases

| Fase | Nombre                              | Rama                            | Casos | Qué queda funcionando                                                       |
| ---- | ----------------------------------- | ------------------------------- | ----- | --------------------------------------------------------------------------- |
| F0   | Entorno y base transversal          | `fase/F0-entorno`               | 7     | Proyecto, errores `{code, detail}`, logs, `/health`, contenedores, CI       |
| F1   | Edificios, taquillas y seguridad    | `fase/F1-edificios-y-taquillas` | 12    | Claves de API y roles, alta de edificios y taquillas, capacidad             |
| F2   | Reserva bajo concurrencia           | `fase/F2-reserva-concurrente`   | 9     | Reservar sin doble asignación, con dos réplicas                             |
| F3   | Idempotencia y migración con datos  | `fase/F3-idempotencia`          | 11    | `Idempotency-Key`; migración de `country` con datos                         |
| F4   | Depositar, recoger y consultar      | `fase/F4-depositar-y-recoger`   | 14    | Ciclo de vida de la entrega; el depósito escribe el evento                  |
| F5   | Worker y notificador                | `fase/F5-worker-y-notificador`  | 12    | Aviso al residente con reintentos; sistema completo                         |
| F6   | Caducidad de reservas               | `fase/F6-caducidad`             | 11    | Las reservas que no se depositan caducan y liberan su taquilla              |

Cada fase deja `main` en verde y es utilizable por sí sola. Orden fijo: F0 → F1 → F2 → F3 → F4 → F5 → F6.

---

## 3. F0 — Entorno y base transversal

**Rama:** `fase/F0-entorno`  ·  **Depende de:** nada.

### Objetivo

Dejar el proyecto arrancando con la infraestructura de bookstore adaptada y lo transversal que usarán todas las fases:
formato de errores, logs, identificador de petición, `/health`, contenedores con dos réplicas, CI e infraestructura de
tests. Todavía no hay ningún dominio.

### Alcance

**Dentro**

- Clonar bookstore **fuera** del repositorio (`/tmp/bookstore`) y adaptar de él: `pyproject.toml` (nombre `locker`; las
  mismas dependencias), `.python-version` (3.14.8), `.gitignore`, `.dockerignore`, `.vscode/settings.json`,
  `alembic.ini`, `migrations/env.py` y `script.py.mako`, `Dockerfile`, `compose.yml`, `Makefile`,
  `.github/workflows/ci.yml`, `tests/integration/conftest.py`, `tests/e2e/conftest.py`.
- `src/locker/core/`: `config.py`, `database.py`, `exceptions.py`, `exception_handlers.py`, `logging.py`, `middleware.py`.
- `src/locker/main.py`: lifespan, app global, manejadores, middleware y `GET /health`.
- `.env.example`, `README.md` (puesta en marcha y tabla de comandos) y `uv.lock`.

**Fuera:** `core/security.py` (F1), cualquier dominio, cualquier migración (no hay modelos), el servicio `worker` de
Compose (F5).

### Detalles de implementación

- `core/config.py` define **dos** clases: `DatabaseSettings` (`database_url`, `sql_echo`) y `Settings(DatabaseSettings)`,
  que añade `log_level`. `migrations/env.py` usa `DatabaseSettings`, para que Alembic no exija las demás variables.
  Las demás variables se añaden en la fase que las usa: `API_KEYS` en F1, `PICKUP_CODE_SECRET` en F4 y `OUTBOX_*` en F5.
- `core/database.py`: igual que bookstore, ampliando `NAMING_CONVENTION` con `"ck"` (§5.1). `create_engine` recibe un
  `DatabaseSettings`, de modo que acepta también un `Settings`. Los tests que solo necesitan la base de datos (por
  ejemplo, F0-02 con la URL inalcanzable) construyen `DatabaseSettings(...)` y no dependen de las variables de fases posteriores.
- `core/exceptions.py`: `DomainError` (con atributos `code` y `detail`) y las familias `NotFoundError`, `ConflictError`,
  `ForbiddenError`, `UnauthenticatedError`, `UnprocessableError` y `ServiceUnavailableError`.
- `core/exception_handlers.py`: registra un manejador por familia (HTTP 404, 409, 403, 401, 422, 503) con cuerpo
  `{code, detail}`, y convierte `RequestValidationError` en `422 VALIDATION_ERROR` con `detail` en texto (§8.1).
- `core/middleware.py`: middleware ASGI del identificador de petición (§7.11). `core/logging.py`: formateador JSON y
  `configure_logging` (§7.11).
- `GET /health`: §7.12. Devuelve `ServiceUnavailableError` (503) si la base de datos no responde.
- Compose (§13.2): `db`, `migrate`, `api-1` y `api-2`, con `env_file: .env`. Makefile (§13.3): `e2e` y `smoke` con
  `BASE_URLS` (lista separada por comas). `make migrate` ejecuta sin error aunque no haya migraciones.

### Tests (7 casos)

| ID    | Nivel | Qué comprueba                                                                                               | Fichero sugerido                                   |
| ----- | ----- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| F0-01 | I     | `/health` responde `200 {"status": "ok"}` con Postgres disponible                                           | `tests/integration/test_health_api.py`             |
| F0-02 | I     | `/health` responde `503` con `{"code": "SERVICE_UNAVAILABLE", ...}` sin base de datos (URL inalcanzable, sin dobles) | `tests/integration/test_health_api.py`    |
| F0-03 | U     | Cada familia de error se traduce a su HTTP y a `{code, detail}` (404, 409, 403, 401, 422, 503), en una app en memoria | `tests/unit/test_exception_handlers.py`     |
| F0-04 | U     | El error de validación de FastAPI se convierte en `422 VALIDATION_ERROR` con `detail` en texto legible       | `tests/unit/test_exception_handlers.py`            |
| F0-05 | I     | Toda respuesta lleva `X-Request-ID`, distinto en cada petición                                              | `tests/integration/test_request_id_api.py`         |
| F0-06 | U     | El formateador escribe una línea JSON válida con `ts`, `level`, `logger`, `message`, `request_id` y los extras | `tests/unit/test_logging.py`                    |
| F0-07 | E     | Smoke: `/health` da `200` en cada réplica de `BASE_URLS`                                                    | `tests/e2e/test_smoke.py`                          |

### Criterios de aceptación

- **AC1.** `uv sync --locked` funciona; `make check` pasa sin dejar cambios.
- **AC2.** `make test` pasa con F0-01 a F0-06.
- **AC3.** `make e2e` levanta `db`, migra y arranca `api-1` y `api-2`; F0-07 pasa contra los puertos 8001 y 8002.
- **AC4.** Con `make up` y `make run`, `curl -i localhost:8000/health` da `200` y trae `X-Request-ID`; con la base de
  datos parada (`make stop`) da `503` con el formato de error.
- **AC5.** No existe ninguna carpeta de dominio ni ninguna dependencia fuera de §10.
- **AC6.** El README explica cómo ponerlo en marcha desde cero (`cp .env.example .env`, `uv sync`, `make up`, ...).
- **AC7.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `build:` proyecto: `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `.dockerignore`, `.vscode`.
2. `build:` Makefile, `alembic.ini` y `migrations/` (con `DatabaseSettings`).
3. `feat:` configuración, base de datos y lifespan (`core/config.py`, `core/database.py`, `main.py`).
4. `test:` infraestructura de pytest y fixtures de integración. `ci:` GitHub Actions con `make check` y `make test`.
5. `test:` errores `{code, detail}` (rojo) → `feat:` familias de errores y manejadores.
6. `test:` `/health` con y sin base de datos (rojo) → `feat:` endpoint `/health`.
7. `test:` identificador de petición y logs JSON (rojo) → `feat:` middleware y logging.
8. `build:` Dockerfile y Compose (`db`, `migrate`, `api-1`, `api-2`).
9. `test:` fixtures E2E y smoke; `build:` objetivos `e2e` y `smoke`.
10. `docs:` README con puesta en marcha y comandos.

### Puntos críticos de la revisión

El lifespan y la separación `DatabaseSettings`/`Settings`; el manejador central de errores; que `/health` falla de verdad
sin base de datos; los healthchecks y el orden de arranque de Compose.

---

## 4. F1 — Edificios, taquillas y seguridad

**Rama:** `fase/F1-edificios-y-taquillas`  ·  **Depende de:** F0.

### Objetivo

Que el operador pueda crear edificios y dar de alta taquillas con etiqueta generada, y que cualquier cliente pueda
consultar la capacidad, todo protegido con claves de API y roles.

### Alcance

**Dentro**

- `core/security.py` (§7.1) y la variable `API_KEYS` en `Settings`, con sus validaciones (§12.1) y `.env.example`.
- Paquete `buildings/` (alta de edificio: §7.2) y paquete `lockers/` (alta de taquillas: §7.3; capacidad: §7.4), con
  los siete ficheros de siempre.
- Migraciones 1 (`buildings`) y 2 (`lockers`) con sus restricciones e índice parcial (§5.2, §5.3).
- Los routers registrados en `main.py` bajo `/v1`; `migrations/env.py` importa los modelos.
- Fixtures de test para clientes autenticados (cabeceras del operador y de transportistas).

**Fuera:** `country`, entregas, cualquier endpoint de transportista (F2 en adelante).

### Detalles de implementación

- `Settings.api_keys` es una lista de entradas (`key`, `role`, `name`) leída del JSON de `API_KEYS`. La validación está en
  el modelo de configuración (§12.1).
- `lockers.service` usa `buildings.repository` para bloquear la fila del edificio (`FOR UPDATE`).
- La etiqueta es `f"{size}-{n:02d}"`. Es una función pura, testeable aparte.
- La capacidad es la consulta agrupada de §7.4; el orden `S`, `M`, `L` puede hacerse en Python o con SQL.
- `session.begin()` es lo primero del alta de taquillas. La dependencia de autenticación no consulta la base de datos.

### Tests (12 casos)

| ID    | Nivel | Qué comprueba                                                                                                         | Fichero sugerido                                       |
| ----- | ----- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| F1-01 | U     | Validación de `API_KEYS` (parametrizado): lista válida; `carrier` sin `name`; claves repetidas; rol inválido; clave corta | `tests/unit/test_settings_api_keys.py`             |
| F1-02 | U     | Formato de la etiqueta: `S-01`, `M-03`, `L-12`, `M-100`                                                               | `tests/unit/test_labels.py`                            |
| F1-03 | I     | Sin clave o con clave inválida → `401 UNAUTHENTICATED` (parametrizado)                                                | `tests/integration/test_security_api.py`               |
| F1-04 | I     | Rol equivocado → `403 FORBIDDEN` (un transportista no crea edificios ni taquillas)                                    | `tests/integration/test_security_api.py`               |
| F1-05 | I     | El operador crea un edificio (`201`, `id` y `name`, espacios recortados); nombre vacío → `422 VALIDATION_ERROR`. Desde F3 la respuesta incluye también `country`, y la aserción pasa a esperar `"country": "ES"`        | `tests/integration/test_buildings_api.py`              |
| F1-06 | I     | Alta de taquillas: etiquetas consecutivas por talla, todas `FREE`; `quantity > 1`; las tallas llevan contadores independientes | `tests/integration/test_lockers_api.py`      |
| F1-07 | I     | `quantity` fuera de rango o talla inválida → `422`; edificio inexistente → `404 NOT_FOUND`                            | `tests/integration/test_lockers_api.py`                |
| F1-08 | I     | Dos altas simultáneas de la misma talla → etiquetas `M-03` y `M-04`, sin errores ni duplicados. **Segundo caso:** una transacción aparte retiene la fila del edificio sin confirmar y el alta por la API se queda esperando; al confirmar, termina con `201` (el primer caso puede pasar por azar sin el bloqueo)                        | `tests/integration/test_lockers_concurrency.py`        |
| F1-09 | I     | Capacidad desglosada por talla (total y libres, con taquillas `BUSY` puestas por SQL), ordenada `S`, `M`, `L`          | `tests/integration/test_capacity_api.py`               |
| F1-10 | I     | Capacidad: edificio sin taquillas → `sizes: []`; inexistente → `404`; un transportista puede consultarla              | `tests/integration/test_capacity_api.py`               |
| F1-11 | I     | Los `CHECK` de `size` y `status` rechazan valores inválidos (repositorio directo, `constraint_name` correcto)          | `tests/integration/test_lockers_repository.py`         |
| F1-12 | I     | Modelos y migraciones coinciden (`alembic check`); las migraciones bajan y suben en vacío. Es un test **genérico** (usa `head`): cubre también las migraciones de las fases siguientes y no se repite | `tests/integration/test_migrations.py` |

### Criterios de aceptación

- **AC1.** `make check` y `make test` pasan; F1-01 a F1-12 existen y no quedan `xfail`.
- **AC2.** Con el sistema en marcha y las claves de `.env.example`: el operador crea un edificio y 3 taquillas `M` y
  obtiene `M-01`, `M-02` y `M-03`; la capacidad devuelve `{"size": "M", "total": 3, "free": 3}`.
- **AC3.** Sin clave, las operaciones de `/v1` devuelven `401` con el formato de error.
- **AC4.** La tabla `lockers` tiene `uq_lockers_building_id_label`, `ck_lockers_size`, `ck_lockers_status` e
  `ix_lockers_free_by_size` (parcial). Se comprueba en el test de migraciones o con `make psql`.
- **AC5.** `make e2e` sigue en verde.
- **AC6.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `test:` validación de `API_KEYS` (rojo) → `feat:` claves de API en la configuración.
2. `test:` autenticación y roles (rojo) → `feat:` `core/security.py`.
3. `test:` etiqueta con formato (rojo) → `feat:` función de etiqueta.
4. `feat:` migración y modelo de `buildings`; `test:` alta de edificio (rojo) → `feat:` paquete `buildings`.
5. `feat:` migración y modelo de `lockers`; `test:` alta de taquillas, incluida la simultánea (rojo) → `feat:` paquete
   `lockers` (alta con bloqueo del edificio).
6. `test:` capacidad (rojo) → `feat:` capacidad por talla.
7. `test:` `CHECK` de `lockers` y migraciones (rojo/verde según proceda).
8. `docs:` README (claves de API y ejemplo de uso).

### Puntos críticos de la revisión

`core/security.py` (comparación en tiempo constante y `auto_error=False`); la alta de taquillas: el bloqueo del edificio,
`begin()` primero y el test de dos altas simultáneas; la consulta de capacidad; el índice parcial de la migración.

---

## 5. F2 — Reserva bajo concurrencia

**Rama:** `fase/F2-reserva-concurrente`  ·  **Depende de:** F1.

### Objetivo

Reservar una taquilla de una talla sin que dos transportistas puedan quedarse con la misma, ni siquiera con dos réplicas
de la API.

### Alcance

**Dentro**

- Migración 3 (`deliveries`) con `uq_deliveries_active_locker`, `uq_deliveries_active_package` y `ck_deliveries_status`.
- Paquete `deliveries/` (modelos, schemas, repositorio, servicio, router, dependencias, excepciones) con **solo** el
  endpoint `POST /v1/deliveries`.
- En `lockers/repository`: la asignación atómica de taquilla (§7.5, paso 4).
- Errores `NoLockerAvailableError` y `DuplicatePackageError`.
- Fixtures/ayudantes de test: edificios con taquillas y `reservar(...)`.

**Fuera:** `Idempotency-Key` (F3), depositar, recoger y consultar (F4), el evento (F4).

### Detalles de implementación

- El flujo es §7.5 **sin los pasos 1, 2 y 6** (idempotencia). Orden: edificio → asignar taquilla → crear entrega.
- La asignación es **una sola sentencia** con CTE y `FOR UPDATE SKIP LOCKED` (I3), construida con SQLAlchemy (por ejemplo
  `select(...).with_for_update(skip_locked=True).limit(1).cte(...)` y `update(...).where(...).returning(...)`). El orden
  es `ORDER BY id` (UUID v7: la más antigua primero).
- `deliveries.repository` traduce el `IntegrityError` de `uq_deliveries_active_package` (SQLSTATE `23505` y nombre de la
  restricción) a `DuplicatePackageError`, **sin** `rollback` (I5). Cualquier otra violación se relanza.
- `session.begin()` es lo primero del servicio. El `carrier` sale del `Principal`.
- Esquemas de §8.4: `extra="forbid"`, `str_strip_whitespace=True`. Respuesta: la entrega de §8.4 (`deposited_at` y
  `picked_up_at` nulos).
- El ayudante `reservar` de los tests se usará también en F3 (que le añadirá la cabecera).

### Tests (9 casos)

| ID    | Nivel | Qué comprueba                                                                                                         | Fichero sugerido                                       |
| ----- | ----- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| F2-01 | I     | Reservar asigna una taquilla libre de la talla pedida: `201`, taquilla `BUSY`, entrega `PENDING` en la base de datos    | `tests/integration/test_reservation_api.py`           |
| F2-02 | I     | Sin taquilla libre de esa talla → `409 NO_LOCKER_AVAILABLE` sin rastro; **no** asigna una talla mayor aunque haya libres | `tests/integration/test_reservation_api.py`         |
| F2-03 | I     | Edificio inexistente → `404`; sin clave → `401`; operador → `403`; cuerpo inválido (talla, referencia vacía, campo extra) → `422` (parametrizado) | `tests/integration/test_reservation_api.py` |
| F2-04 | I     | Paquete duplicado (mismo transportista y referencia, entrega activa) → `409 DUPLICATE_PACKAGE`; la taquilla no queda ocupada | `tests/integration/test_reservation_api.py`    |
| F2-05 | I     | La misma referencia de **otro** transportista es una reserva distinta y se permite                                     | `tests/integration/test_reservation_api.py`           |
| F2-06 | I     | 10 reservas simultáneas para 5 taquillas libres → exactamente 5 × `201` y 5 × `409`, con 5 taquillas distintas y 5 entregas. **Segundo caso:** con una taquilla bloqueada por otra reserva todavía sin confirmar, una reserva nueva no espera: salta esa taquilla y se queda con la siguiente al momento. El primer caso no distingue `SKIP LOCKED` de `FOR UPDATE` a secas (con ambos salen 5 y 5; la diferencia es que sin `SKIP LOCKED` las reservas van en fila) | `tests/integration/test_reservation_concurrency.py` |
| F2-07 | I     | Los índices únicos parciales frenan el insert directo en la base de datos: segunda entrega activa para la misma taquilla y para el mismo paquete (comprobando `constraint_name`) | `tests/integration/test_deliveries_repository.py` |
| F2-08 | I     | Una entrega `PICKED_UP` no cuenta como activa: se puede crear otra para la misma taquilla y el mismo paquete            | `tests/integration/test_deliveries_repository.py`     |
| F2-09 | E     | **Concurrencia entre réplicas:** edificio nuevo con 5 taquillas; 10 reservas repartidas entre `api-1` y `api-2` con hilos → exactamente 5 éxitos con taquillas distintas | `tests/e2e/test_replicas_concurrency.py` |

### Criterios de aceptación

- **AC1.** `make check` y `make test` pasan; F2-01 a F2-08 existen y no quedan `xfail`; el test de migraciones genérico (F1-12) cubre `deliveries`.
- **AC2.** `make e2e` pasa, incluido F2-09 (el smoke sigue verde).
- **AC3.** La asignación es una única sentencia SQL (I3): ninguna ruta de código hace `SELECT` y luego `UPDATE` para reservar.
- **AC4.** Tras un `409`, no queda ninguna fila nueva en `deliveries` ni ninguna taquilla `BUSY` de más.
- **AC5.** Los repositorios no llaman a `commit` ni a `rollback` (I5).
- **AC6.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `feat:` migración y modelo de `deliveries` (índices únicos parciales y `CHECK`).
2. `test:` índices únicos y entregas no activas (rojo → verde, directos a la base de datos): F2-07 y F2-08.
3. `test:` reserva: camino feliz (rojo) → `feat:` asignación de taquilla y servicio de reserva.
4. `test:` sin taquilla, talla mayor, edificio inexistente y roles (rojo) → `feat:` errores y validaciones.
5. `test:` paquete duplicado y otro transportista (rojo) → `feat:` traducción del `IntegrityError` a `DuplicatePackageError`.
6. `test:` reservas simultáneas (rojo → verde): F2-06.
7. `test:` E2E de concurrencia entre réplicas (F2-09).
8. `docs:` README (reservar).

### Puntos críticos de la revisión

La sentencia de asignación (CTE, `SKIP LOCKED`, una sola sentencia); la traducción del `IntegrityError` sin `rollback`;
que `begin()` va primero; los tests F2-06 y F2-09: qué prueban y por qué son dos niveles.

---

## 6. F3 — Idempotencia y migración con datos

**Rama:** `fase/F3-idempotencia`  ·  **Depende de:** F2.

### Objetivo

Que reintentar una reserva no cree una segunda, y demostrar una migración que cambia una tabla con datos sin perderlos.

### Alcance

**Dentro**

- Paquete `idempotency/` (`__init__.py`, `models.py`, `repository.py`, `exceptions.py`, `dependencies.py` y
  `fingerprint.py`; sin `router.py`, `schemas.py` ni `service.py`) y la migración 4 (`idempotency_keys`).
- `deliveries.service`: añade los pasos 1, 2 y 6 de §7.5 y la cabecera `Idempotency-Key` obligatoria.
- Migración 5: `country` en `buildings` con expand → backfill → contract (§5.8). `buildings` pasa a aceptar y devolver
  `country`.
- Los ayudantes de test de F2 (`reservar`) pasan a enviar siempre `Idempotency-Key` (clave nueva por llamada si no se
  indica). **Es el único cambio permitido en tests de F2.**

**Fuera:** depositar, recoger, consultar, el evento.

### Detalles de implementación

- Huella: §7.5 paso 1. Vive en `idempotency/fingerprint.py`, función pura.
- Registro de la clave: `INSERT ... ON CONFLICT (carrier, key) DO NOTHING RETURNING` (con el `insert` de
  `sqlalchemy.dialects.postgresql`). Si no devuelve fila, se lee la existente y se compara la huella.
- El servicio hace `UPDATE idempotency_keys SET response_body = ...` al final y guarda **la respuesta serializada** de la
  entrega (JSON), que es lo que se devuelve en un reintento.
- `IdempotencyKeyReusedError` es `UnprocessableError` (`422`, `IDEMPOTENCY_KEY_REUSED`).
- La cabecera falta → `422 VALIDATION_ERROR` por la validación de FastAPI (`Header(...)`, 1 a 255 caracteres).
- Migración de `country`: §5.8. El test de migración fija como **constantes** los identificadores de la revisión
  anterior a `country` y de la propia `country` (no usa `head`, porque en F4 habrá una migración posterior).
- `BuildingIn` acepta `country` opcional (por defecto `ES`, dos mayúsculas); `Building` lo devuelve.

### Tests (11 casos)

| ID    | Nivel | Qué comprueba                                                                                                         | Fichero sugerido                                       |
| ----- | ----- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| F3-01 | U     | Huella: el mismo cuerpo da la misma huella aunque cambie el orden de los campos; un cuerpo distinto, otra huella       | `tests/unit/test_fingerprint.py`                       |
| F3-02 | I     | Misma clave y mismo cuerpo → `201` con la **misma respuesta**, y una sola entrega y una sola taquilla ocupada          | `tests/integration/test_idempotency_api.py`            |
| F3-03 | I     | Misma clave y otro cuerpo → `422 IDEMPOTENCY_KEY_REUSED`, sin cambios                                                  | `tests/integration/test_idempotency_api.py`            |
| F3-04 | I     | Dos peticiones **idénticas simultáneas** → una sola entrega y dos `201` iguales. **Segundo caso (determinista):** una transacción aparte registra la clave sin confirmar; la reserva idéntica por la API espera y, al confirmar la otra con su respuesta guardada, devuelve `201` con exactamente esa respuesta, sin crear ninguna entrega                                        | `tests/integration/test_idempotency_concurrency.py`    |
| F3-05 | I     | Clave nueva y mismo paquete → `409 DUPLICATE_PACKAGE`, y la clave **no** queda guardada                                | `tests/integration/test_idempotency_api.py`            |
| F3-06 | I     | Falta `Idempotency-Key` → `422 VALIDATION_ERROR`                                                                       | `tests/integration/test_idempotency_api.py`            |
| F3-07 | I     | Una reserva fallida no guarda la clave: tras `409 NO_LOCKER_AVAILABLE` y liberar una taquilla, el reintento con la misma clave funciona | `tests/integration/test_idempotency_api.py` |
| F3-08 | I     | La clave es por transportista: la misma clave de dos transportistas da dos entregas independientes                      | `tests/integration/test_idempotency_api.py`            |
| F3-09 | I     | El reintento devuelve la respuesta **original** aunque la entrega haya cambiado de estado (se cambia por SQL)           | `tests/integration/test_idempotency_api.py`            |
| F3-10 | I     | **Migración con datos:** se migra hasta la revisión anterior, se insertan edificios, se migra a la de `country`: se conservan y quedan con `ES`; bajar y volver a subir conserva los datos | `tests/integration/test_migrations.py` |
| F3-11 | I     | `POST /v1/buildings` con `country` opcional (por defecto `ES`) y respuesta con `country`; formato inválido → `422`; `ck_buildings_country_format` rechaza `es` y `E1` en la base de datos (`ESP` no llega al `CHECK`: la columna es `varchar(2)` y se rechaza antes por longitud, SQLSTATE `22001`) | `tests/integration/test_buildings_api.py` |

### Criterios de aceptación

- **AC1.** `make check` y `make test` pasan; F3-01 a F3-11 existen y no quedan `xfail`. Los tests de F2 siguen pasando y el test de migraciones genérico (F1-12) cubre `idempotency_keys` y `country`.
- **AC2.** `make e2e` sigue en verde.
- **AC3.** `POST /v1/deliveries` sin `Idempotency-Key` da `422`.
- **AC4.** La migración de `country` tiene `upgrade` con las tres etapas (expand, backfill, contract) comentadas, y
  `downgrade`.
- **AC5.** Ninguna reserva fallida deja una fila en `idempotency_keys` (I8).
- **AC6.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `test:` huella (rojo) → `feat:` `fingerprint.py`.
2. `feat:` migración, modelo y repositorio de `idempotency_keys`.
3. `test:` ayudantes de reserva con `Idempotency-Key` (adaptación de los tests de F2).
4. `test:` idempotencia: reintento, cuerpo distinto, paquete duplicado y cabecera (rojo) → `feat:` flujo de idempotencia en la reserva.
5. `test:` simultáneas idénticas (rojo → verde): F3-04.
6. `test:` clave por transportista, reserva fallida y respuesta original (rojo → verde): F3-07 a F3-09.
7. `test:` migración de `country` con datos (rojo) → `feat:` migración `country` (expand → backfill → contract).
8. `feat:` `country` en la API de edificios, con sus tests.
9. `docs:` README (idempotencia y país).

### Puntos críticos de la revisión

El orden de pasos del flujo de reserva y por qué la segunda petición idéntica espera; la huella canónica; que lo que se
guarda es la respuesta original; la migración de `country` (expand → backfill → contract) y su test con datos.

---

## 7. F4 — Depositar, recoger y consultar

**Rama:** `fase/F4-depositar-y-recoger`  ·  **Depende de:** F3.

### Objetivo

Completar el ciclo de vida de la entrega: el transportista deposita (y se apunta el evento en la misma transacción), el
residente recoge con el código derivado, y el transportista consulta su entrega.

### Alcance

**Dentro**

- `deliveries/pickup_code.py` (§7.9) y la variable `PICKUP_CODE_SECRET` en `Settings` (mínimo 32 caracteres) y
  `.env.example`.
- Paquete `outbox/` **parcial**: `models.py`, `repository.py` (solo `add`), `events.py`; migración 6 (`outbox_events`).
  Todavía **no** hay `service.py`, `notifier.py` ni `worker.py`.
- Endpoints `POST /v1/deliveries/{id}/deposit`, `GET /v1/deliveries/{id}` y `POST /v1/deliveries/{id}/pickup`.
- Liberación de la taquilla en `lockers/repository`.
- E2E del flujo completo.

**Fuera:** el worker, el notificador y cualquier envío (F5).

### Detalles de implementación

- Depositar: §7.6. Recoger: §7.7 (orden: existe → estado → código → `UPDATE` condicional → liberar taquilla).
- `pickup_code.derive(secret, delivery_id)` y `matches(secret, delivery_id, candidate)` (§7.9). El secreto llega por
  `get_settings`.
- El `UPDATE` condicional de depositar lleva `carrier = :carrier`: el transportista solo opera sobre sus entregas.
- Para `deposit`, si el `UPDATE` no afecta a ninguna fila hay que leer la entrega del mismo transportista para decidir
  entre `404`, `200` (ya depositada) y `409` (§7.6).
- El evento es `type="delivery.deposited"`, `payload={"delivery_id": "<uuid>"}`; el `id` de la fila es el `event_id`.
- El `GET` y la respuesta de `pickup` usan la misma entrega de §8.4 (con `building_id`, `locker_label` y `size`, que
  salen de unir `deliveries` con `lockers`).
- **E2E:** el test calcula el código con `pickup_code.derive` y el secreto de `Settings` (leída de `.env`); no lo lee de
  ningún log.

### Tests (14 casos)

| ID    | Nivel | Qué comprueba                                                                                                         | Fichero sugerido                                       |
| ----- | ----- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| F4-01 | U     | Código de recogida: determinista; 6 dígitos con ceros a la izquierda; distinto por `id` y por secreto; `matches` acepta el correcto y rechaza el incorrecto | `tests/unit/test_pickup_code.py` |
| F4-02 | I     | Depositar: `PENDING` → `DEPOSITED`, con `deposited_at` y `200`                                                         | `tests/integration/test_deposit_api.py`                |
| F4-03 | I     | Depositar escribe el evento `delivery.deposited` con `payload.delivery_id`, en la misma transacción                     | `tests/integration/test_deposit_api.py`                |
| F4-04 | I     | Depositar dos veces → `200` y **un solo** evento. **Segundo caso:** otra transacción hace el depósito sin confirmar; el depósito por la API espera y, al confirmar, responde `200` con un solo evento                                                                        | `tests/integration/test_deposit_api.py`                |
| F4-05 | I     | Depositar entrega ajena o inexistente → `404`; entrega `PICKED_UP` → `409 INVALID_STATE`; operador → `403`              | `tests/integration/test_deposit_api.py`                |
| F4-06 | I     | Atomicidad: dentro de una transacción, si algo falla después de depositar, ni el estado ni el evento persisten (sin dobles). **Segundo caso (servicio):** un `trigger` real de PostgreSQL hace fallar el `INSERT` del evento; depositar por la API falla y la entrega sigue `PENDING` | `tests/integration/test_deposit_transaction.py`   |
| F4-07 | I     | Consultar: la propia → `200`; ajena o inexistente → `404`; operador → `403`                                             | `tests/integration/test_deliveries_api.py`             |
| F4-08 | I     | Recoger con el código correcto → `200`, `PICKED_UP`, `picked_up_at` y la taquilla vuelve a `FREE`                       | `tests/integration/test_pickup_api.py`                 |
| F4-09 | I     | Código incorrecto → `403 INVALID_PICKUP_CODE` y nada cambia; mal formado → `422`; entrega inexistente → `404`. El código son exactamente seis cifras `[0-9]` (no `\d`, que acepta cifras de otros alfabetos)           | `tests/integration/test_pickup_api.py`                 |
| F4-10 | I     | Recoger una entrega sin depositar, o recoger dos veces → `409 INVALID_STATE`. Recoger con un código incorrecto una entrega sin depositar → `409` (el estado se comprueba antes que el código)                                            | `tests/integration/test_pickup_api.py`                 |
| F4-11 | I     | Dos recogidas simultáneas con el código correcto → una `200` y una `409`. **Segundo caso:** otra transacción hace el `UPDATE` a `PICKED_UP` sin confirmar; la recogida por la API espera y, al confirmar, responde `409`                                                | `tests/integration/test_pickup_concurrency.py`         |
| F4-12 | I     | El código no aparece como valor en ninguna respuesta (reservar, depositar, consultar, recoger), ni en los registros de log al recoger con un código incorrecto                           | `tests/integration/test_pickup_api.py`                 |
| F4-13 | I     | Ciclo completo: tras recoger, la taquilla puede volver a reservarse                                                     | `tests/integration/test_pickup_api.py`                 |
| F4-14 | E     | Flujo completo contra el sistema: reservar, depositar y recoger con el código derivado                                   | `tests/e2e/test_delivery_flow.py`                      |

### Criterios de aceptación

- **AC1.** `make check` y `make test` pasan; F4-01 a F4-13 existen y no quedan `xfail`. Los tests de fases anteriores pasan y el test de migraciones genérico (F1-12) cubre `outbox_events`.
- **AC2.** `make e2e` pasa, incluido F4-14.
- **AC3.** Ningún repositorio, schema, evento ni log (salvo el futuro notificador) contiene el código de recogida (I7).
- **AC4.** Depositar y la fila del evento son atómicos: F4-06 lo demuestra sin dobles de prueba.
- **AC5.** La tabla `outbox_events` tiene las columnas de §5.6 y ningún índice.
- **AC6.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `test:` código de recogida (rojo) → `feat:` `pickup_code.py` y `PICKUP_CODE_SECRET`.
2. `feat:` migración 6, modelo, repositorio (`add`) y `events.py` de `outbox`.
3. `test:` depositar: transición, evento, repetido y errores (rojo) → `feat:` endpoint de depositar.
4. `test:` atomicidad del depósito (rojo → verde): F4-06.
5. `test:` consultar (rojo) → `feat:` endpoint de consulta.
6. `test:` recoger: caminos feliz y de error (rojo) → `feat:` endpoint de recoger y liberación de la taquilla.
7. `test:` recogidas simultáneas, el código ausente de las respuestas y el ciclo completo (rojo → verde).
8. `test:` E2E del flujo completo (F4-14).
9. `docs:` README (ciclo de la entrega y variables de entorno).

### Puntos críticos de la revisión

El `UPDATE` condicional y cómo se decide entre `404`, `200` y `409`; el orden de comprobaciones de recoger y la carrera de
dos recogidas; `pickup_code.py` (HMAC y `compare_digest`); que el evento se escribe en la misma transacción.

---

## 8. F5 — Worker y notificador

**Rama:** `fase/F5-worker-y-notificador`  ·  **Depende de:** F4.

### Objetivo

Que el depósito avise al residente de forma fiable: un worker toma los eventos del outbox, los entrega con reintentos y
deja los fallidos reactivables. Con esta fase el núcleo queda completo.

### Alcance

**Dentro**

- Variables `OUTBOX_MAX_ATTEMPTS`, `OUTBOX_BACKOFF_BASE_SECONDS` y `OUTBOX_POLL_INTERVAL_SECONDS` en `Settings` y
  `.env.example`.
- `outbox/notifier.py` (`Notification`, `Notifier` y `LogNotifier`), `outbox/service.py` (`process_next`) y
  `outbox/worker.py` (bucle, señales y arranque).
- `outbox/repository.py`: toma del evento, borrado y registro de fallo.
- Servicio `worker` en `compose.yml` y objetivo `make worker`.
- `NotificadorFalso` (única excepción a «sin dobles», §14.3) en `tests/integration/`.
- README: el worker y el SQL para reactivar eventos muertos.

**Fuera:** broker, envíos reales, eventos nuevos, alertas.

### Detalles de implementación

- `process_next` es exactamente §7.10: una transacción por evento, `FOR UPDATE SKIP LOCKED`, éxito → borrar, fallo →
  registrar y **confirmar** (no relanzar). La espera se calcula en la base de datos con `now()`.
- Las reglas de espera y agotamiento son **funciones puras** (`outbox/service.py` o un módulo hermano), para testearlas
  en unitario.
- `Notification` lleva `event_id`, `delivery_id`, `recipient`, `building_name`, `locker_label`, `pickup_code` y `message`.
  El worker obtiene estos datos con `deliveries.repository` y `pickup_code.derive`.
- `LogNotifier` usa el logger `locker.notifier` con `extra={"event_id": ..., "delivery_id": ...}`.
- `worker.py`: `asyncio.Event` de parada activado por `SIGINT`/`SIGTERM`; engine y fábrica de sesiones propios;
  `configure_logging`; un error inesperado en `process_next` se registra y el bucle continúa tras la pausa.
- `NotificadorFalso` implementa `Notifier`, **graba** cada notificación y falla cuando se le configura (antes o
  después de grabar).
- En los tests, `OUTBOX_BACKOFF_BASE_SECONDS=0` (el evento vuelve a estar vencido al instante) salvo en los que
  comprueban que la espera es futura.
- **E2E:** el test consulta `outbox_events` con `asyncpg` (la URL de `Settings` sin el sufijo `+asyncpg`) hasta que la
  tabla queda vacía, con un máximo de 10 s.

### Tests (12 casos)

| ID    | Nivel | Qué comprueba                                                                                                         | Fichero sugerido                                       |
| ----- | ----- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| F5-01 | U     | Espera tras el fallo n = base × 2^(n − 1) (2, 4, 8 y 16 s con base 2; 0 con base 0); regla de agotamiento: al alcanzar el máximo, el evento queda muerto       | `tests/unit/test_outbox_retry_rules.py`                |
| F5-02 | I     | Envío correcto: el notificador recibe `event_id`, destinatario, taquilla, edificio y el **código correcto**; la fila se borra y `process_next` devuelve `True` | `tests/integration/test_outbox_service.py` |
| F5-03 | I     | Cola vacía → `False` sin efectos; un evento con `next_attempt_at` futuro no se toma                                      | `tests/integration/test_outbox_service.py`            |
| F5-04 | I     | Fallo del notificador: `attempts` = 1 y `next_attempt_at` en el futuro; el evento sigue en la tabla                      | `tests/integration/test_outbox_service.py`            |
| F5-05 | I     | Cinco fallos seguidos → evento muerto (`attempts` = 5 y `next_attempt_at` nulo), y `process_next` ya no lo toma          | `tests/integration/test_outbox_service.py`            |
| F5-06 | I     | Reactivar un evento muerto con el `UPDATE` documentado → se procesa y se borra                                           | `tests/integration/test_outbox_service.py`            |
| F5-07 | I     | Dos workers a la vez con N eventos → cada evento se notifica **exactamente una vez** y la tabla queda vacía. **Segundo caso:** otra transacción bloquea el evento más antiguo sin confirmar; `process_next` procesa el siguiente sin esperar y, después, devuelve `False` con el bloqueado intacto             | `tests/integration/test_outbox_concurrency.py`        |
| F5-08 | I     | Reenvío: el notificador graba y luego falla; en la siguiente pasada se envía de nuevo **con el mismo `event_id`**         | `tests/integration/test_outbox_service.py`            |
| F5-09 | I     | Un evento cuya entrega no existe cuenta como fallo y el bucle sigue                                                      | `tests/integration/test_outbox_service.py`            |
| F5-10 | I     | `LogNotifier` escribe una línea JSON con `event_id`, `delivery_id` y el mensaje. Y el `repr` del aviso no contiene el código                                          | `tests/integration/test_log_notifier.py`              |
| F5-11 | I     | El worker se detiene al pedirlo, sin esperar a la pausa completa. **Segundo caso:** contra una base de datos sin migrar, el bucle registra el error y sigue vivo; al migrar, procesa un evento                                                         | `tests/integration/test_worker.py`                    |
| F5-12 | E     | Tras depositar contra el sistema real, el worker envía el aviso y borra el evento de esa entrega (≤ 10 s)                                                | `tests/e2e/test_worker_drains_outbox.py`              |

### Criterios de aceptación

- **AC1.** `make check` y `make test` pasan; F5-01 a F5-11 existen y no quedan `xfail`. Los tests de fases anteriores pasan.
- **AC2.** `make e2e` pasa, incluido F5-12, con `api-1`, `api-2` y `worker` en marcha.
- **AC3.** Con `make up`, `make migrate`, `make run` y `make worker`, depositar una entrega hace que el worker escriba en
  su log una línea JSON con el aviso (y se vea el `event_id`).
- **AC4.** Un fallo registrado confirma la transacción (la fila se actualiza); un éxito borra la fila (§7.10).
- **AC5.** El README documenta el `UPDATE` que reactiva eventos muertos.
- **AC6.** No hay ningún `time.sleep` ni `asyncio.sleep` en los tests de reintentos.
- **AC7.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `test:` reglas de espera y agotamiento (rojo) → `feat:` funciones puras y `OUTBOX_*` en la configuración.
2. `feat:` `notifier.py` (`Notification`, `Notifier`, `LogNotifier`) y `NotificadorFalso`.
3. `test:` `process_next`: éxito, vacío y no vencido (rojo) → `feat:` toma y borrado del evento.
4. `test:` fallo, agotamiento y reactivación (rojo) → `feat:` registro de fallo y estado muerto.
5. `test:` dos workers a la vez y reenvío con el mismo `event_id` (rojo → verde): F5-07 y F5-08.
6. `test:` evento sin entrega y `LogNotifier` (rojo → verde).
7. `test:` parada del worker (rojo) → `feat:` `worker.py` (bucle y señales) y `make worker`.
8. `build:` servicio `worker` en Compose; `test:` E2E del worker.
9. `docs:` README (worker y reactivación de eventos muertos).

### Puntos críticos de la revisión

`process_next`: la transacción, el `SKIP LOCKED` y por qué el fallo **confirma** en vez de relanzar; el cálculo de la
espera; el test de dos workers a la vez; el bucle y el apagado del worker; que el evento no lleva el código.

---

## 9. Cierre del núcleo

Tras fusionar F5, quedan tareas **fuera de Claude Code** que completan el núcleo:

1. **README final**: puesta en marcha, comandos, ejemplos de uso con `curl`, reactivación de eventos muertos y la lista de
   limitaciones (§3).
2. **`docs/decisiones_arquitectura.pdf`**: el porqué de cada decisión (§15), pensado para el VP y el equipo técnico, con
   tono humano y diagramas. Incluye el argumento de no tener broker de mensajes y la explicación de la diferencia con
   bookstore (la transacción vive en el servicio).
3. **Repaso de cobertura** de los siete requisitos de la oferta (§1.1), con lo que se enseña de cada uno y lo que queda
   sin cubrir (en particular, el CD).
4. **F6 añadida** (§10); el despliegue en GCP se especificará aparte.

---

## 10. F6 — Caducidad de reservas

**Rama:** `fase/F6-caducidad`  ·  **Depende de:** F5.

### Objetivo

Que una reserva que no se deposita no bloquee la taquilla para siempre.

### Alcance

**Dentro**

- Variable `RESERVATION_TTL_SECONDS` en `Settings` y `.env.example` (§12.1).
- Migración 7, «añadir caducidad a deliveries» (§5.8), y el modelo de `deliveries`: columna `expires_at` y estado
  `EXPIRED` (§5.4).
- Fijar `expires_at` al reservar (§7.5, paso 5).
- `deliveries/expiration.py` con `ExpirationService.expire_next` (§7.13) y el método de `deliveries/repository` que
  ejecuta la sentencia de caducidad.
- El segundo trabajo del bucle del worker (§7.10).
- El tratamiento de `EXPIRED` al depositar, recoger y consultar (§7.6, §7.7, §8.4).
- README: la caducidad y `RESERVATION_TTL_SECONDS`.

**Fuera:** eventos o avisos de caducidad, exponer `expires_at`, TTL por transportista o por edificio, el despliegue.

### Detalles de implementación

- `RESERVATION_TTL_SECONDS` es un entero mayor que 0, por defecto 1800 (`Field` con `gt=0`). Llega al servicio de
  reserva por `Settings`, igual que el secreto del código de recogida.
- `expires_at` se calcula en la base de datos con `now()` más el TTL (A12), nunca con el reloj de Python.
- Migración 7: §5.8, con expand, backfill y contract comentados, y el `downgrade` con la pérdida asumida explicada en un
  comentario. El test de la migración con datos fija como **constantes** los identificadores de la revisión de
  `outbox_events` y de la de caducidad (no usa `head`).
- `expire_next` es exactamente §7.13: `session.begin()` es lo primero; la caducidad es **una sola sentencia** (el CTE
  con `FOR UPDATE SKIP LOCKED` y el `UPDATE` condicional); la liberación de la taquilla reutiliza `release` de
  `lockers/repository` y va en la misma transacción (I14); si no cambia la taquilla, error inesperado y se deshace
  todo, como al recoger. Los repositorios no hacen `commit` ni `rollback` (I5).
- `ExpirationService` recibe la sesión, el repositorio de entregas y el de taquillas; no llama a servicios de otros
  dominios (§9.2). La caducidad escribe un log `INFO` con el `delivery_id`; no hay evento.
- El `status` de los schemas admite `EXPIRED`. `expires_at` no se añade a ningún schema de respuesta (AC5).
- Depositar (§7.6): si el `UPDATE` no devuelve fila y la entrega del mismo transportista está `DEPOSITED`, `200` tal
  cual; cualquier otro estado (`PICKED_UP` o `EXPIRED`), `409 INVALID_STATE`.
- `worker.py`: una función hermana de `process_one` (por ejemplo `expire_one`) abre su propia sesión y ejecuta
  `expire_next`. En el bucle, cada tarea va en su propio `try/except`: un error inesperado en una no impide la otra ni
  mata el proceso. El módulo, el comando de arranque y el logger no cambian.
- El ayudante `insertar_entrega` de `tests/integration/test_deliveries_repository.py` pasa a rellenar `expires_at`: es
  el único cambio permitido en los tests de fases anteriores.
- En los tests no hay esperas: la caducidad se provoca fijando `expires_at` en la fila por SQL.

### Tests (11 casos)

| ID    | Nivel | Qué comprueba                                                                                                         | Fichero sugerido                                       |
| ----- | ----- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| F6-01 | U     | `RESERVATION_TTL_SECONDS` vale 1800 por defecto, acepta un entero mayor que 0 y rechaza 0 y negativos                  | `tests/unit/test_settings_reservation_ttl.py`          |
| F6-02 | I     | Reservar fija `expires_at` en la base de datos dentro de la ventana `now()` más TTL, y el cuerpo de la respuesta no incluye `expires_at` | `tests/integration/test_reservation_api.py` |
| F6-03 | I     | `expire_next` pasa una entrega `PENDING` vencida a `EXPIRED` y su taquilla a `FREE` en la misma transacción, y devuelve `True` | `tests/integration/test_expiration_service.py` |
| F6-04 | I     | No caduca lo que no toca (`PENDING` no vencida, `DEPOSITED` con `expires_at` pasado, `PICKED_UP`) y devuelve `False` sin efectos | `tests/integration/test_expiration_service.py` |
| F6-05 | I     | Tras caducar, el mismo paquete y la misma taquilla pueden reservarse otra vez y la capacidad cuenta la taquilla como libre | `tests/integration/test_expiration_service.py` |
| F6-06 | I     | Depositar o recoger una entrega `EXPIRED` → `409 INVALID_STATE`; consultarla → `200` con `status` `EXPIRED`              | `tests/integration/test_expiration_api.py`             |
| F6-07 | I     | Carrera depositar contra caducar sobre entregas vencidas, repetida varias veces: gana exactamente uno y el estado final es coherente (`DEPOSITED` con la taquilla `BUSY`, o `EXPIRED` con la taquilla `FREE`; nunca otra combinación) | `tests/integration/test_expiration_concurrency.py` |
| F6-08 | I     | Dos workers a la vez con N entregas vencidas (N ≤ 10): cada una caduca exactamente una vez y todas las taquillas quedan `FREE` | `tests/integration/test_expiration_concurrency.py` |
| F6-09 | I     | **Migración con datos:** se migra hasta la revisión de `outbox_events`, se insertan entregas `PENDING`, `DEPOSITED` y `PICKED_UP`, se migra a la de caducidad: las `PENDING` reciben `expires_at` y las demás quedan en NULL; el `CHECK` rechaza una `PENDING` sin `expires_at` y admite `EXPIRED`; el `downgrade` pasa las `EXPIRED` a `PICKED_UP` y quita la columna; volver a subir funciona | `tests/integration/test_migrations.py` |
| F6-10 | I     | El bucle del worker ejecuta las dos tareas (outbox y caducidad) y un error inesperado en una no impide la otra; los tests de F5-11 siguen pasando | `tests/integration/test_worker.py` |
| F6-11 | E     | Una reserva caduca de verdad en el sistema en contenedores: se reserva, se fuerza `expires_at` al pasado por SQL con el engine de SQLAlchemy (`create_engine(get_settings())` y `text(...)`, como F5-12, porque `asyncpg` no trae información de tipos y no pasa mypy estricto) y se espera, con un máximo de 10 s, a que la consulta devuelva `EXPIRED` | `tests/e2e/test_reservation_expiry.py` |

### Criterios de aceptación

- **AC1.** `make check` y `make test` pasan; F6-01 a F6-10 existen y no quedan `xfail`. El test de migraciones genérico
  (F1-12) cubre la migración 7.
- **AC2.** `make e2e` pasa, incluido F6-11.
- **AC3.** La caducidad es una sola sentencia `UPDATE` condicional y la liberación de la taquilla va en la misma
  transacción (I14).
- **AC4.** Los tests de fases anteriores pasan sin editarse, salvo el ayudante `insertar_entrega` (excepción declarada
  arriba).
- **AC5.** Ninguna respuesta incluye `expires_at`.
- **AC6.** El README documenta `RESERVATION_TTL_SECONDS` y la caducidad.
- **AC7.** Se cumple la definición de «hecho» (§1.2).

### Orden de commits

1. `test:` `RESERVATION_TTL_SECONDS` (rojo) → `feat:` la variable en la configuración (F6-01).
2. `test:` migración de caducidad con datos (rojo) → `feat:` migración 7, modelo y estado `EXPIRED` (F6-09).
3. `test:` fijar `expires_at` al reservar (rojo) → `feat:` plazo de la reserva (F6-02).
4. `test:` `expire_next` (rojo) → `feat:` `ExpirationService.expire_next` y su repositorio (F6-03 a F6-05).
5. `test:` `EXPIRED` al depositar, recoger y consultar (rojo) → `feat:` su tratamiento y el `status` de los schemas
   (F6-06).
6. `test:` carrera con depositar y dos workers a la vez (rojo → verde): F6-07 y F6-08.
7. `test:` bucle del worker con las dos tareas (rojo) → `feat:` segundo trabajo del worker (F6-10).
8. `test:` E2E de la caducidad (F6-11).
9. `docs:` README (caducidad y `RESERVATION_TTL_SECONDS`).

### Puntos críticos de la revisión

La sentencia de caducidad (CTE, `SKIP LOCKED`, `UPDATE` condicional) y la liberación de la taquilla en la misma
transacción; la carrera con depositar; la migración con datos y su `downgrade` con pérdida asumida; el bucle del worker
con dos tareas independientes.
