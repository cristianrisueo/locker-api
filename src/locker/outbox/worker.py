# Worker del outbox: un proceso aparte, con el mismo código que la API, que envía los avisos pendientes.
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.core.config import Settings
from locker.outbox.notifier import Notifier


async def run(
    session_factory: async_sessionmaker[AsyncSession], notifier: Notifier, settings: Settings, stop: asyncio.Event
) -> None:
    """Bucle del worker, hasta que se active stop."""
    raise NotImplementedError
