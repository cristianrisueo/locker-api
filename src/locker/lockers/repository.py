# Repositorio de taquillas: define la interfaz y su implementación sobre PostgreSQL.
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from locker.lockers.schemas import Locker, Size


class LockerRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Cuenta las taquillas de un edificio de una talla
    async def count(self, building_id: uuid.UUID, size: Size) -> int: ...

    # Inserta una taquilla libre por etiqueta y las devuelve en el mismo orden
    async def add_many(self, building_id: uuid.UUID, size: Size, labels: list[str]) -> list[Locker]: ...


class SqlLockerRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def count(self, building_id: uuid.UUID, size: Size) -> int:
        """Cuántas taquillas de esa talla tiene el edificio."""
        raise NotImplementedError

    async def add_many(self, building_id: uuid.UUID, size: Size, labels: list[str]) -> list[Locker]:
        """Inserta las taquillas en un solo INSERT y las devuelve tal como quedaron en la tabla."""
        raise NotImplementedError
