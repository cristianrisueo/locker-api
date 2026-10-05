# Capa de servicio de taquillas: alta de taquillas con etiqueta generada y consulta de capacidad.
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.exceptions import BuildingNotFoundError
from locker.buildings.repository import BuildingRepository
from locker.lockers.repository import LockerRepository
from locker.lockers.schemas import Capacity, LockersCreated, LockersIn, Size


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
        """
        Da de alta taquillas de una talla con etiquetas consecutivas. Si el edificio no existe, 404.
        En una transacción, con la fila del edificio bloqueada (I12): dos altas simultáneas en el mismo
        edificio se ponen en fila, así que la segunda cuenta también las taquillas que acaba de crear la primera
        """

        # La transacción es lo primero del caso de uso, antes de cualquier consulta
        async with self._session.begin():
            # 1. Bloquea el edificio: otra alta en el mismo edificio espera aquí hasta que esta confirme
            if not await self._buildings.lock(building_id):
                raise BuildingNotFoundError(building_id)

            # 2. Cuenta las taquillas que ya hay de esta talla: la numeración sigue a partir de ahí
            existing = await self._lockers.count(building_id, data.size)

            # 3. Inserta las nuevas, numeradas desde existing + 1
            labels = [make_label(data.size, existing + n) for n in range(1, data.quantity + 1)]
            lockers = await self._lockers.add_many(building_id, data.size, labels)

        return LockersCreated(lockers=lockers)

    async def capacity(self, building_id: uuid.UUID) -> Capacity:
        """Capacidad del edificio por talla, en orden S, M, L. Si el edificio no existe, 404."""
        raise NotImplementedError
