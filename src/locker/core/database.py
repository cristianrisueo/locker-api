# Conexión a la base de datos.
# Este archivo define cómo se construyen el pool de conexiones y las sesiones, y la base de las tablas.
# No crea nada al importarse: el engine se construye en el lifespan de la app (main.py).
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from locker.core.config import DatabaseSettings

# Convención de nombres para índices, restricciones únicas, claves foráneas y CHECK.
# Así todas tienen un nombre predecible y Alembic puede borrarlas al deshacer una migración.
# En los CHECK, constraint_name es el nombre corto que se da en el modelo: "size" -> ck_lockers_size
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """
    Base es la clase de la que heredan todas las tablas.
    Al heredar, cada tabla queda registrada, y así Alembic sabe qué tablas existen.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """
    ENGINE: el pool de conexiones a Postgres. Hay uno solo para toda la aplicación.
    Crearlo no conecta todavía: las conexiones se abren cuando hacen falta y se reutilizan.
    Recibe un DatabaseSettings, así que también acepta un Settings (que hereda de él)
    """
    return create_async_engine(settings.database_url, echo=settings.sql_echo)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    FÁBRICA DE SESIONES: crea sesiones ya configuradas, para no repetir la configuración.
    expire_on_commit=False: tras guardar los cambios (commit), los objetos conservan
    sus valores en memoria. Si no, Python intentaría releerlos de la base de datos
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """
    Dependencia de FastAPI: una sesión por petición, que se cierra al terminar.
    La fábrica la deja el lifespan en app.state; en los tests se sustituye con dependency_overrides.
    """
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
