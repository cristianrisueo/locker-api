# Capa de servicio de taquillas: alta de taquillas con etiqueta generada y consulta de capacidad.
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.repository import BuildingRepository
from locker.lockers.repository import LockerRepository
from locker.lockers.schemas import LockersCreated, LockersIn, Size


def make_label(size: Size, number: int) -> str:
    """Etiqueta de una taquilla: la talla y el número con dos cifras como mínimo (M-03, M-100)."""
    # :02d rellena con ceros a la izquierda hasta dos cifras; con más cifras no recorta nada
    return f"{size}-{number:02d}"


class LockerService:
    def __init__(self, session: AsyncSession, lockers: LockerRepository, buildings: BuildingRepository) -> None:
        """
        Recibe la sesión de la petición (para abrir la transacción) y los repositorios que la usan:
        el de taquillas y el de edificios, que comparten esa misma sesión
        """
        self._session = session
        self._lockers = lockers
        self._buildings = buildings

    async def create(self, building_id: uuid.UUID, data: LockersIn) -> LockersCreated:
        """Da de alta taquillas de una talla con etiquetas consecutivas. Si el edificio no existe, 404."""
        raise NotImplementedError
