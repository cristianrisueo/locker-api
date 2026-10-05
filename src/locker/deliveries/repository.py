# Repositorio de entregas: define la interfaz y su implementación sobre PostgreSQL.
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.schemas import Delivery, ReservationIn
from locker.lockers.schemas import Locker


class DeliveryRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Crea una entrega PENDING en la taquilla asignada y la devuelve completa
    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery: ...


class SqlDeliveryRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery:
        raise NotImplementedError
