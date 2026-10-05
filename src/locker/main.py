# Punto de entrada de la aplicación FastAPI.
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.router import router as buildings_router
from locker.core.config import get_settings
from locker.core.database import create_engine, create_session_factory, get_session
from locker.core.exception_handlers import register_exception_handlers
from locker.core.exceptions import ServiceUnavailableError
from locker.core.logging import configure_logging
from locker.core.middleware import RequestIdMiddleware
from locker.deliveries.router import router as deliveries_router
from locker.lockers.router import router as lockers_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Ciclo de vida de la app: lo anterior al yield se ejecuta al arrancar y lo posterior al apagar.
    Al arrancar: lee la configuración (si falta DATABASE_URL, API_KEYS o PICKUP_CODE_SECRET, o alguna no es
    válida, la app no arranca), configura los logs en JSON y crea el pool.
    Al apagar: cierra las conexiones del pool de forma ordenada.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

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

# Añade a cada respuesta la cabecera X-Request-ID y deja el identificador disponible para los logs
app.add_middleware(RequestIdMiddleware)

# Añade los routers de los dominios bajo /v1 (versionado en la ruta). /health queda fuera: no es parte del contrato
app.include_router(buildings_router, prefix="/v1")
app.include_router(lockers_router, prefix="/v1")
app.include_router(deliveries_router, prefix="/v1")


@app.get("/health", responses={503: {"description": "La base de datos no responde"}})
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    """
    Comprueba si la API responde y llega a la base de datos. Si no, devuelve 503.
    Un único endpoint sirve de comprobación de vida y de disponibilidad (no hay /health/ready)
    """

    # Si la base de datos tarda más de 2 segundos, se da por caída. Comprueba conexiones rechazadas y timeouts.
    try:
        async with asyncio.timeout(2):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise ServiceUnavailableError("Base de datos no disponible") from exc

    return {"status": "ok"}
