# Capa de servicio de edificios: abre la transacción y usa el repositorio.
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
        raise NotImplementedError
