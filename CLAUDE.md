# Locker API

API de taquillas para paquetería: un transportista reserva una taquilla de un edificio, deposita el paquete y el
residente lo recoge con un código. Python 3.14 + FastAPI + PostgreSQL. Se construye por fases con Claude Code.
Es una pieza de portfolio: debe ser pequeña, correcta y fácil de explicar.

## Fuentes de verdad

- `docs/especificaciones.md`: qué hace el sistema y cómo se construye (modelo de datos, invariantes, contrato HTTP,
  decisiones). Se cita por sección: «§7.5».
- `docs/plan_fases.md`: las fases (F0 a F5), con alcance, tests, criterios de aceptación y orden de commits.
- Este fichero: convenciones de trabajo y de código.

Lee las secciones que necesites cuando las necesites. Si el código y las especificaciones no coinciden, **para y
avisa**: no sigas a ninguna de las dos en silencio. No edites `docs/especificaciones.md` ni `docs/plan_fases.md`.

Repositorio de referencia (público): <https://github.com/cristianrisueo/bookstore>. Es la API de práctica de la que sale
la infraestructura de este proyecto. Si una fase lo pide, clónalo **fuera** de este repositorio (por ejemplo en
`/tmp/bookstore`) para copiar y adaptar ficheros. No lo añadas al repositorio.

## Cómo se trabaja

1. **Una sesión por fase.** Haz solo la fase que te indiquen. No empieces la siguiente ni adelantes trabajo.
2. **Una rama por fase**: `fase/F<N>-<nombre>`, creada desde `main`. Nunca trabajes en `main`, nunca fusiones, nunca
   hagas push a `main`. Al terminar, sube la rama; el desarrollador abre la PR, revisa y fusiona.
3. **Esqueletos, tests en rojo, implementación.** Para cada comportamiento:
   1. Crea los esqueletos (clases y funciones que lanzan `NotImplementedError`) para que los tests **importen** y
      fallen por aserción, nunca por `ImportError`.
   2. Escribe el test y comprueba que falla por la razón esperada. Márcalo
      `@pytest.mark.xfail(strict=True, reason="...")` y haz commit (`test: ...`). El CI sigue en verde.
   3. Implementa lo mínimo para que pase, **quita el `xfail`** y haz commit (`feat: ...` o `fix: ...`).
      Con `strict=True`, un test que pasa con el marcador falla: es la señal de que toca quitarlo.
4. **Antes de cada commit**: `make check` (formatea, linter y tipos). Antes de subir: `make test` y, si la fase lo
   pide, `make e2e`.
5. **Al terminar**, resume en pocas líneas: qué has hecho, qué no, y qué dudas o decisiones tomaste.

## Entorno y comandos

Python 3.14.8 y **uv**. Nunca `pip`, nunca `python -m venv`. Todo se lanza por Makefile; escribe `make` para ver la lista.

| Comando                       | Qué hace                                                                |
| ----------------------------- | ----------------------------------------------------------------------- |
| `make up` / `stop` / `down`   | Levanta, apaga o elimina el contenedor de PostgreSQL                    |
| `make destroy`                | Elimina el contenedor **y los datos**. No lo ejecutes sin que te lo pidan |
| `make psql`                   | Consola SQL dentro de la base de datos                                  |
| `make migrate` / `rollback`   | Aplica las migraciones pendientes o deshace la última                   |
| `make migration m="mensaje"`  | Genera una migración desde los modelos                                  |
| `make run`                    | API con recarga en <http://127.0.0.1:8000>                              |
| `make worker`                 | Arranca el worker del outbox en local (desde F5)                        |
| `make check`                  | `ruff format`, `ruff check` y `mypy` (estricto)                         |
| `make test`                   | Unitarios + integración (necesita Docker, usa testcontainers)           |
| `make test-unit`              | Solo unitarios, sin Docker                                              |
| `make coverage`               | Tests con informe de cobertura (señal, sin umbral)                      |
| `make e2e`                    | Levanta el sistema en contenedores, migra y pasa E2E + smoke            |
| `make smoke BASE_URLS=...`    | Smoke contra un sistema ya levantado                                    |

## Reglas de código

- **Un paquete por dominio** en `src/locker/`, siempre con los mismos ficheros: `router.py`, `schemas.py`,
  `dependencies.py`, `service.py`, `repository.py`, `models.py`, `exceptions.py`. Lo transversal vive en `core/`.
  Estructura completa en `docs/especificaciones.md` §11.
- **Schemas de Pydantic (API) y modelos de SQLAlchemy (tablas) separados.** El repositorio traduce de uno a otro.
- **Repositorios como `Protocol`** con una implementación `Sql...Repository`. **Los repositorios nunca hacen `commit`
  ni `rollback`**: solo ejecutan consultas.
- **La transacción la abre el servicio**, con `async with self._session.begin():` como **primera** operación del caso
  de uso (antes de cualquier consulta, o SQLAlchemy ya habrá abierto una transacción y `begin()` fallará). Las
  lecturas simples no necesitan `begin()`. Un servicio puede usar repositorios de otros dominios (comparten la sesión
  de la petición) pero no llama a servicios de otros dominios.
- **Errores de dominio sin HTTP**, heredando de las familias de `core/exceptions.py`. Solo `core/exception_handlers.py`
  decide qué código HTTP corresponde. Todo error de la API tiene la forma `{"code": "...", "detail": "..."}`.
- **Estados con `UPDATE` condicional** (`WHERE status = <origen>`) mirando las filas afectadas. Nunca leer el estado
  en Python para decidir. La unicidad la imponen las restricciones de la base de datos, no una consulta previa.
- **Identificadores**: UUID v7 con `uuid.uuid7()` (Python 3.14), generado en la aplicación.
- **Sin dependencias nuevas.** La lista es cerrada (`docs/especificaciones.md` §10). Si crees que falta una, para y
  avisa.
- **Nada que no esté pedido.** Ni campos, ni endpoints, ni capas, ni abstracciones «por si acaso». Un dato que nadie
  usa es código muerto.
- **Migraciones**: solo con Alembic (`make migration`). Una migración que ya está en `main` nunca se edita, se añade
  otra. Todas tienen `downgrade`. Los cambios sobre tablas con datos siguen expand → backfill → contract.
- Ruff con línea de 125 caracteres y mypy estricto: el código pasa los dos sin ignorar reglas.
- Secretos (claves de API, secreto del código de recogida) **nunca** en logs, respuestas ni commits.

## Estilo de comentarios

**Los comentarios, docstrings y mensajes de commit van en castellano**; los identificadores del código, en inglés.
Se escriben para alguien que está aprendiendo: explican **qué hace cada paso** en lenguaje llano y **por qué** cuando
la razón no es evidente. Copia el estilo de bookstore. Estos son los patrones:

**1. Cabecera de fichero:** una línea que dice qué es el fichero, y una segunda si hace falta.

```python
# Repositorio de libros: Define la interfaz y su implementación sobre PostgreSQL.
# Conexión a la base de datos.
# Este archivo define cómo se construyen el pool de conexiones y las sesiones, y la base de las tablas.
# No crea nada al importarse: el engine se construye en el lifespan de la app (main.py).
```

**2. Docstrings:** de una línea si basta; si no, con salto de línea tras las comillas.

```python
def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    FÁBRICA DE SESIONES: crea sesiones ya configuradas, para no repetir la configuración.
    expire_on_commit=False: tras guardar los cambios (commit), los objetos conservan
    sus valores en memoria. Si no, Python intentaría releerlos de la base de datos
    """
```

**3. Comentarios paso a paso dentro de las funciones**, en lenguaje llano:

```python
        # Crea un modelo de SQLAlchemy a partir del schema de Pydantic que viene de la API
        model = BookModel(title=data.title, author_id=data.author_id, pages=data.pages)

        # Lo apunta en la sesión y hace commit para que se guarde en la base de datos
        self._session.add(model)
```

**4. Comentarios de «por qué»** cuando algo no es obvio (una restricción, un código de error, una trampa):

```python
# Código SQLSTATE de PostgreSQL para una clave foránea que apunta a una fila inexistente
FOREIGN_KEY_VIOLATION = "23503"

    # OSError cubre la conexión rechazada (asyncpg no siempre la envuelve) y TimeoutError
    except (SQLAlchemyError, OSError) as exc:
```

**5. Modelos: un comentario por columna o restricción**, diciendo qué es y por qué existe:

```python
    # Restricción en la tabla: pages es un número positivo.
    # Pydantic ya lo valida en la API, pero así la tabla se protege aunque alguien
    # escriba en ella por otro camino (un script, una migración, otro servicio)
    __table_args__ = (CheckConstraint("pages > 0", name="ck_books_pages_positive"),)

    title: Mapped[str] = mapped_column(String(255))  # String de hasta 255 caracteres, NOT NULL
```

**6. Migraciones:** docstring que explica el patrón y comentarios por fase.

```python
    # Expand: columna nueva, todavía admite NULL para no fallar con libros existentes
    op.add_column("books", sa.Column("author_id", sa.Integer(), nullable=True))
    # Backfill: ...
    # Contract: ya rellena, se exige, se relaciona y se elimina la columna antigua
```

**7. Tests:** nombre en castellano que describe el comportamiento, docstring con el porqué, y helpers en castellano.

```python
async def test_obtener_libro_inexistente_devuelve_404(client: AsyncClient) -> None:
    """BookNotFoundError se traduce a 404 con un detail legible."""
    respuesta = await client.get("/books/999")

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "Book 999 not found"}
```

Mensajes de error al cliente (`detail`): en castellano, tal como figuran en `docs/especificaciones.md` §8.3.

## Tests

- **Tres niveles.** Unitario (lógica pura, sin E/S, sin Docker), integración (servicio, repositorio o la API en el
  mismo proceso, contra **PostgreSQL real**) y E2E (sistema en contenedores; muy pocos). Cada comportamiento se prueba
  en el **nivel más bajo que cace su bug**.
- **Siempre PostgreSQL real y efímero** (testcontainers, imagen `postgres:18`, la misma que `compose.yml`). El esquema
  se crea con `alembic upgrade head` en un subproceso, como `make migrate`. Aislamiento entre tests con
  `TRUNCATE ... RESTART IDENTITY CASCADE`. Nunca SQLite, nunca la base de datos de desarrollo.
- La API en el mismo proceso se prueba con `httpx` y `ASGITransport`. Cada petición recibe una **sesión nueva**, como en
  producción (en `tests/integration/conftest.py`, la fixture `client`).
- **Sin dobles de prueba**, con una única excepción: `NotificadorFalso` (graba lo que recibe y falla cuando se le
  pide), porque un fallo de un sistema externo no se puede provocar de verdad. Cualquier otro doble, no.
- **Sin `sleep`**. La espera entre reintentos es configurable y los tests la ponen a 0, o modifican
  `next_attempt_at` en la fila.
- Las pruebas de concurrencia usan varias sesiones y `asyncio.gather` (N ≤ 10 peticiones simultáneas: el pool por
  defecto admite 15 conexiones). Entre procesos reales, solo en E2E.
- Aserciones sobre el contenido de las respuestas (`respuesta.json() == {...}`), no solo sobre el código HTTP.
- Los casos obligatorios de cada fase y su nivel están en `docs/plan_fases.md`. La cobertura es una señal, sin umbral.

## Git

- Mensajes de commit en castellano, en minúsculas y con prefijo: `feat:`, `fix:`, `test:`, `refactor:`, `build:`,
  `ci:`, `docs:`. Con verbo en infinitivo: `test: reproducir la pérdida de datos al relacionar books con authors`.
- Commits pequeños, uno por paso del orden que marca el plan. Sin `--force`. Sin `--amend` de commits ya subidos.
- La rama se sube al terminar con `git push -u origin fase/F<N>-<nombre>`.

## Lo que no se hace

- No `docker compose down -v` ni `make destroy` por tu cuenta: borran los datos.
- No tocar `main`, no fusionar, no cambiar `.github/` más allá de lo que pida la fase.
- No añadir dependencias, campos, endpoints o ficheros fuera de lo que describen las especificaciones.
- No dejar `xfail`, `print`, código comentado ni `TODO` en lo que se sube.
- No inventar el comportamiento ante una duda: pregunta o deja constancia en el resumen final.
