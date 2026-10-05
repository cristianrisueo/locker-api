# Repositorio de edificios: define la interfaz y su implementación sobre PostgreSQL.
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.schemas import Building, BuildingIn


class BuildingRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Añade un edificio nuevo y lo devuelve con su id
    async def add(self, data: BuildingIn) -> Building: ...


class SqlBuildingRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def add(self, data: BuildingIn) -> Building:
        """Inserta un edificio y lo devuelve con el id generado."""
        raise NotImplementedError
