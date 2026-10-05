# Salud: /health comprueba de verdad la conexión con la base de datos.
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from locker.core.config import DatabaseSettings
from locker.core.database import create_engine, create_session_factory, get_session
from locker.main import app

# Nada escucha en el puerto 1: la conexión se rechaza de verdad, sin dobles ni parar contenedores
URL_INALCANZABLE = "postgresql+asyncpg://x:x@127.0.0.1:1/x"


@pytest.mark.xfail(strict=True, raises=NotImplementedError, reason="Falta el endpoint /health")
async def test_health_devuelve_200_con_bd(client: AsyncClient) -> None:
    """«[F0-01]» Con Postgres disponible, /health ejecuta SELECT 1 y responde 200."""
    respuesta = await client.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


@pytest.mark.xfail(strict=True, raises=NotImplementedError, reason="Falta el endpoint /health")
async def test_health_devuelve_503_sin_bd(client: AsyncClient) -> None:
    """
    «[F0-02]» Si la base de datos no responde, /health da 503 SERVICE_UNAVAILABLE con la forma de error común:
    ni se traga el error (200) ni lo deja escapar (500).
    """
    engine = create_engine(DatabaseSettings(database_url=URL_INALCANZABLE, _env_file=None))
    session_factory = create_session_factory(engine)

    async def session_sin_bd() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    # Sustituye la sesión que puso la fixture client; la fixture retira la sustitución al terminar
    app.dependency_overrides[get_session] = session_sin_bd
    try:
        respuesta = await client.get("/health")
    finally:
        await engine.dispose()

    assert respuesta.status_code == 503
    assert respuesta.json() == {"code": "SERVICE_UNAVAILABLE", "detail": "Base de datos no disponible"}
