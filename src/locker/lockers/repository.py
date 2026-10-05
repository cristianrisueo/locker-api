# Repositorio de taquillas: define la interfaz y su implementación sobre PostgreSQL.
import uuid
from typing import Protocol

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from locker.lockers.models import LockerModel
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
        stmt = (
            select(func.count())
            .select_from(LockerModel)
            .where(LockerModel.building_id == building_id, LockerModel.size == size)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def add_many(self, building_id: uuid.UUID, size: Size, labels: list[str]) -> list[Locker]:
        """Inserta las taquillas en un solo INSERT y las devuelve tal como quedaron en la tabla."""

        # Una fila por etiqueta. El id (UUID v7) lo genera la aplicación; el estado FREE lo pone la base de datos
        rows = [{"building_id": building_id, "label": label, "size": size} for label in labels]

        # INSERT ... RETURNING: devuelve las filas completas, también el estado que puso la base de datos.
        # sort_by_parameter_order=True garantiza que vuelven en el mismo orden que las etiquetas
        stmt = insert(LockerModel).returning(LockerModel, sort_by_parameter_order=True)
        models = await self._session.scalars(stmt, rows)

        # Convierte los modelos de SQLAlchemy a schemas de Pydantic para devolverlos
        return [Locker.model_validate(model, from_attributes=True) for model in models]
