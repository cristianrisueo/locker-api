# Fixtures de integración: PostgreSQL real y efímero (testcontainers), con el esquema creado por Alembic.
# Ciclo de vida:
#   sesión de pytest -> un contenedor, migrado a head una vez, y un engine compartido
#   cada test        -> sus propias sesiones; al terminar, TRUNCATE de todas las tablas
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Protocol

import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from locker.core.config import ApiKey, DatabaseSettings, Settings, get_settings
from locker.core.database import Base, create_engine, create_session_factory, get_session
from locker.main import app  # importar la app registra todos los modelos en Base.metadata

# Raíz del repositorio, donde está alembic.ini
ROOT = Path(__file__).resolve().parents[2]

# Claves de API de los tests. Solo existen aquí: ni el CI ni `make test` tienen .env, así que los tests
# nunca dependen de la API_KEYS del entorno
CLAVE_OPERADOR = "test-operator-key-000000000"
CLAVE_SEUR = "test-seur-key-0000000000000"
CLAVE_CORREOS = "test-correos-key-00000000000"


class AlembicRunner(Protocol):
    """Lanza un comando de Alembic contra una URL: alembic("postgresql+asyncpg://...", "upgrade", "head")."""

    def __call__(self, url: str, *args: str) -> None: ...


@pytest.fixture(scope="session")
def alembic() -> Iterator[AlembicRunner]:
    """
    Ejecuta Alembic en un subproceso, igual que `make migrate`.
    El cwd es un directorio vacío: así env.py no encuentra ningún .env y solo puede usar la DATABASE_URL que
    le pasamos. Nunca toca la base de datos de desarrollo.
    """
    with tempfile.TemporaryDirectory() as cwd:

        def run(url: str, *args: str) -> None:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
                cwd=cwd,
                env={**os.environ, "DATABASE_URL": url},
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # CalledProcessError no muestra el stderr: se añade como nota para verlo en el informe de pytest
                error = subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
                error.add_note(result.stderr)
                raise error

        yield run


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Contenedor de PostgreSQL con la misma imagen que compose.yml. Se destruye al terminar la sesión."""
    with PostgresContainer("postgres:18", username="test", password="test", dbname="test", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer, alembic: AlembicRunner) -> str:
    """URL del esquema de sesión: la base de datos del contenedor, migrada a head una sola vez."""
    url = postgres.get_connection_url()
    alembic(url, "upgrade", "head")
    return url


@pytest.fixture(scope="session")
async def session_factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """
    El mismo engine y la misma fábrica que crea el lifespan, pero apuntando al contenedor.
    Basta un DatabaseSettings: los tests de base de datos no dependen de las variables de otras fases
    """
    engine = create_engine(DatabaseSettings(database_url=database_url, _env_file=None))
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    """
    Configuración completa de la API para los tests, con claves conocidas. Se construye a mano
    (sin .env) y sustituye a get_settings en la fixture client
    """
    return Settings(
        database_url=database_url,
        api_keys=[
            ApiKey(key=SecretStr(CLAVE_OPERADOR), role="operator"),
            ApiKey(key=SecretStr(CLAVE_SEUR), role="carrier", name="SEUR"),
            ApiKey(key=SecretStr(CLAVE_CORREOS), role="carrier", name="Correos Express"),
        ],
        _env_file=None,
    )


@pytest.fixture
def cabeceras_operador() -> dict[str, str]:
    """Cabeceras de una petición del operador."""
    return {"X-API-Key": CLAVE_OPERADOR}


@pytest.fixture
def cabeceras_transportista() -> dict[str, str]:
    """Cabeceras de una petición del transportista SEUR."""
    return {"X-API-Key": CLAVE_SEUR}


@pytest.fixture
def cabeceras_correos() -> dict[str, str]:
    """Cabeceras de una petición del transportista Correos Express: un segundo transportista distinto de SEUR."""
    return {"X-API-Key": CLAVE_CORREOS}


@pytest.fixture(autouse=True)
async def limpiar_tablas(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """
    Vacía todas las tablas tras cada test. Las tablas salen de los modelos, no de la base de datos,
    para no vaciar alembic_version. El lock_timeout hace que una sesión olvidada abierta falle aquí
    en vez de dejar el TRUNCATE esperando para siempre.
    """
    yield
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with session_factory() as session:
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
    limpiar_tablas: None,
) -> AsyncIterator[AsyncSession]:
    """
    Sesión para los tests de repositorio. Pide limpiar_tablas para crearse después que ella y,
    por tanto, cerrarse antes del TRUNCATE.
    """
    async with session_factory() as s:
        yield s


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> AsyncIterator[AsyncClient]:
    """
    Cliente HTTP contra la app en el mismo proceso. Cada petición recibe una sesión nueva, como en
    producción: si compartiera la del test, el identity map podría ocultar lo que de verdad hay en la BD.
    La configuración es la de la fixture settings, no la del entorno (§7.0).
    """

    async def session_por_peticion() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = session_por_peticion
    app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session)
    app.dependency_overrides.pop(get_settings)


class CrearEdificio(Protocol):
    """Crea un edificio con taquillas por la API: await crear_edificio({"M": 2, "S": 1}) devuelve su id."""

    async def __call__(self, taquillas: dict[str, int]) -> str: ...


@pytest.fixture
def crear_edificio(client: AsyncClient, cabeceras_operador: dict[str, str]) -> CrearEdificio:
    """Ayudante para preparar un edificio con taquillas, como lo haría el operador."""

    async def crear(taquillas: dict[str, int]) -> str:
        respuesta = await client.post("/v1/buildings", json={"name": "Edificio Sol"}, headers=cabeceras_operador)
        assert respuesta.status_code == 201
        edificio: str = respuesta.json()["id"]
        for talla, cuantas in taquillas.items():
            cuerpo = {"size": talla, "quantity": cuantas}
            respuesta = await client.post(f"/v1/buildings/{edificio}/lockers", json=cuerpo, headers=cabeceras_operador)
            assert respuesta.status_code == 201
        return edificio

    return crear


class Reservar(Protocol):
    """Reserva por la API: await reservar(cabeceras, edificio, size="M", tracking_ref="ES123")."""

    async def __call__(
        self,
        cabeceras: dict[str, str],
        building_id: str,
        size: str = "M",
        tracking_ref: str = "ES123",
        recipient: str = "vecino@example.com",
    ) -> Response: ...


@pytest.fixture
def reservar(client: AsyncClient) -> Reservar:
    """Ayudante para lanzar una reserva y devolver la respuesta tal cual, sin comprobar nada."""

    async def lanzar(
        cabeceras: dict[str, str],
        building_id: str,
        size: str = "M",
        tracking_ref: str = "ES123",
        recipient: str = "vecino@example.com",
    ) -> Response:
        cuerpo = {"building_id": building_id, "size": size, "tracking_ref": tracking_ref, "recipient": recipient}
        return await client.post("/v1/deliveries", json=cuerpo, headers=cabeceras)

    return lanzar


@pytest.fixture
async def bd_migraciones(postgres: PostgresContainer) -> AsyncIterator[str]:
    """
    Base de datos vacía y exclusiva de un test, dentro del mismo contenedor. Los tests de migraciones
    bajan y suben el esquema: hacerlo en el esquema de sesión rompería a los demás tests si fallan a medias.
    """
    url = postgres.get_connection_url()
    nombre = f"mig_{uuid.uuid4().hex}"
    # CREATE/DROP DATABASE no pueden ir dentro de una transacción: de ahí AUTOCOMMIT
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{nombre}"'))

    yield make_url(url).set(database=nombre).render_as_string(hide_password=False)

    # WITH (FORCE) cierra las conexiones que un test fallido haya dejado abiertas
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE "{nombre}" WITH (FORCE)'))
    await admin.dispose()
