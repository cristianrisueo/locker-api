# Repositorio del outbox: define la interfaz y su implementación sobre PostgreSQL.
from typing import Any, Protocol

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from locker.outbox.models import OutboxEventModel


class OutboxRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Apunta un evento pendiente de enviar, en la transacción de quien lo llama
    async def add(self, event_type: str, payload: dict[str, Any]) -> None: ...


class SqlOutboxRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def add(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Inserta el evento. El id (UUID v7) lo genera la aplicación; attempts (0) y next_attempt_at (now()) los pone
        la base de datos. Como usa la sesión del servicio, el evento se confirma o se deshace junto con el cambio
        que lo provoca: no puede existir el uno sin el otro
        """
        await self._session.execute(insert(OutboxEventModel).values(type=event_type, payload=payload))
