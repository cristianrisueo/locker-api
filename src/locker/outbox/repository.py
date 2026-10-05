# Repositorio del outbox: define la interfaz y su implementación sobre PostgreSQL.
import uuid
from typing import Any, NamedTuple, Protocol

from sqlalchemy import delete, func, insert, select
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
        """
        Toma el evento vencido más antiguo y lo bloquea hasta que acabe la transacción de quien llama (I13):

        SELECT id, type, payload, attempts FROM outbox_events
        WHERE next_attempt_at <= now()
        ORDER BY next_attempt_at, id
        LIMIT 1
        FOR UPDATE SKIP LOCKED

        Un next_attempt_at nulo (evento muerto) nunca cumple <= now(), y uno futuro todavía no toca.
        SKIP LOCKED: si otro worker tiene bloqueado el más antiguo, no se espera a que termine; se toma el siguiente.
        Así dos workers nunca envían el mismo evento a la vez, y ninguno se queda parado esperando al otro
        """
        stmt = (
            select(OutboxEventModel.id, OutboxEventModel.type, OutboxEventModel.payload, OutboxEventModel.attempts)
            .where(OutboxEventModel.next_attempt_at <= func.now())
            .order_by(OutboxEventModel.next_attempt_at, OutboxEventModel.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        # Convierte la fila al evento, o None si no hay ninguno vencido y libre
        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else OutboxEvent(id=row.id, type=row.type, payload=row.payload, attempts=row.attempts)

    async def delete(self, event_id: uuid.UUID) -> None:
        """
        Borra el evento. La fila ya está bloqueada por take_due en esta misma transacción: nadie más la ha tocado.
        Si la transacción no llega a confirmar, la fila vuelve a estar ahí y el aviso se reenvía (al menos una vez)
        """
        await self._session.execute(delete(OutboxEventModel).where(OutboxEventModel.id == event_id))

    async def record_failure(self, event_id: uuid.UUID, attempts: int, retry_in_seconds: float | None) -> None:
        """Apunta un envío fallido."""
        raise NotImplementedError
