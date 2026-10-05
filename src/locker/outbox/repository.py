# Repositorio del outbox: define la interfaz y su implementación sobre PostgreSQL.
import uuid
from typing import Any, NamedTuple, Protocol

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from locker.outbox.models import OutboxEventModel


class OutboxEvent(NamedTuple):
    """Un evento tomado para enviar: su id (el event_id del aviso), su tipo, su contenido y los fallos que lleva."""

    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    attempts: int


class OutboxRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Apunta un evento pendiente de enviar, en la transacción de quien lo llama
    async def add(self, event_type: str, payload: dict[str, Any]) -> None: ...

    # Toma el evento vencido más antiguo y lo bloquea hasta que acabe la transacción, saltándose los que otro worker
    # tiene bloqueados. None si no hay ninguno
    async def take_due(self) -> OutboxEvent | None: ...

    # Borra el evento: el aviso ya se ha enviado
    async def delete(self, event_id: uuid.UUID) -> None: ...

    # Apunta un envío fallido: el nuevo número de fallos y dentro de cuántos segundos se reintenta (None: evento muerto)
    async def record_failure(self, event_id: uuid.UUID, attempts: int, retry_in_seconds: float | None) -> None: ...


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

    async def take_due(self) -> OutboxEvent | None:
        """Toma el evento vencido más antiguo."""
        raise NotImplementedError

    async def delete(self, event_id: uuid.UUID) -> None:
        """Borra el evento."""
        raise NotImplementedError

    async def record_failure(self, event_id: uuid.UUID, attempts: int, retry_in_seconds: float | None) -> None:
        """Apunta un envío fallido."""
        raise NotImplementedError
