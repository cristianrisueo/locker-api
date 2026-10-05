# Capa de servicio de edificios: Crea edificios
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.repository import BuildingRepository
from locker.buildings.schemas import Building, BuildingIn


class BuildingService:
    def __init__(self, session: AsyncSession, repository: BuildingRepository) -> None:
        """Recibe la sesión de la petición (para abrir la transacción) y el repositorio que la usa."""
        self._session = session
        self._repository = repository

    async def create(self, data: BuildingIn) -> Building:
        """Crea un edificio y lo devuelve con su identificador."""

        # La transacción es lo primero del caso de uso: al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            return await self._repository.add(data)
