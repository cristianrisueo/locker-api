# Punto de entrada de la aplicación FastAPI.
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from locker.core.config import get_settings
from locker.core.database import create_engine, create_session_factory, get_session
from locker.core.exception_handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Ciclo de vida de la app: lo anterior al yield se ejecuta al arrancar y lo posterior al apagar.
    Al arrancar: lee la configuración (si falta DATABASE_URL, la app no arranca) y crea el pool.
    Al apagar: cierra las conexiones del pool de forma ordenada.
    """
    settings = get_settings()

    engine = create_engine(settings)
    app.state.session_factory = create_session_factory(engine)

    try:
        yield
    finally:
        await engine.dispose()


# Crea la aplicación de FastAPI
app = FastAPI(title="Locker API", lifespan=lifespan)

# Registra los manejadores que traducen los errores a respuestas HTTP con la forma {code, detail}
register_exception_handlers(app)


@app.get("/health")
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    """Salud: la API responde y llega a la base de datos. Si no, 503."""
    raise NotImplementedError
