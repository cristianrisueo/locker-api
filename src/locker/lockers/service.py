# Capa de servicio de taquillas: alta de taquillas con etiqueta generada y consulta de capacidad.
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.exceptions import BuildingNotFoundError
from locker.buildings.repository import BuildingRepository
from locker.lockers.repository import LockerRepository
from locker.lockers.schemas import SIZES, Capacity, LockersCreated, LockersIn, Size


def make_label(size: Size, number: int) -> str:
    """Función auxiliar para generar la etiqueta de una taquilla: (M-03, M-100)."""
    return f"{size}-{number:02d}"  # :02d rellena con ceros a la izquierda hasta dos cifras; con más cifras no recorta nada


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
        En una transacción, con la fila del edificio bloqueada: dos altas simultáneas en el mismo
        edificio se ponen en fila, así que la segunda petición cuenta también las taquillas que acaba de crear la primera
        """

        # Ejecuta dentro de una transacción: si algo falla, se hace rollback y no queda nada insertado
        async with self._session.begin():
            # 1. Bloquea el edificio: otra alta en el mismo edificio espera aquí hasta que esta confirme
            if not await self._buildings.lock(building_id):
                raise BuildingNotFoundError(building_id)

            # 2. Cuenta las taquillas que ya hay de esta talla: la numeración sigue a partir de ahí
            existing = await self._lockers.count(building_id, data.size)

            # 3. Crea las etiquetas e inserta las nuevas taquillas, numeradas desde existing + 1
            labels = [make_label(data.size, existing + n) for n in range(1, data.quantity + 1)]
            lockers = await self._lockers.add_many(building_id, data.size, labels)

        return LockersCreated(lockers=lockers)

    async def capacity(self, building_id: uuid.UUID) -> Capacity:
        """
        Capacidad del edificio por talla, en orden S, M, L. Si el edificio no existe, 404.
        Es una lectura simple: no abre transacción
        """

        # Sin esta comprobación, un edificio inexistente parecería un edificio sin taquillas (sizes vacío)
        if not await self._buildings.exists(building_id):
            raise BuildingNotFoundError(building_id)

        # La consulta agrupada no garantiza ningún orden: se ordena aquí por la posición de cada talla en SIZES
        sizes = await self._lockers.capacity(building_id)
        return Capacity(building_id=building_id, sizes=sorted(sizes, key=lambda entry: SIZES.index(entry.size)))
