# Capa de servicio de entregas: reservar una taquilla para un paquete.
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.exceptions import BuildingNotFoundError
from locker.buildings.repository import BuildingRepository
from locker.deliveries.repository import DeliveryRepository
from locker.deliveries.schemas import Delivery, ReservationIn
from locker.lockers.exceptions import NoLockerAvailableError
from locker.lockers.repository import LockerRepository


class DeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        deliveries: DeliveryRepository,
        lockers: LockerRepository,
        buildings: BuildingRepository,
    ) -> None:
        """
        Recibe la sesión de la petición (para abrir la transacción) y los repositorios que la usan:
        el de entregas, el de taquillas y el de edificios, que comparten esa misma sesión
        """
        self._session = session
        self._deliveries = deliveries
        self._lockers = lockers
        self._buildings = buildings

    async def reserve(self, carrier: str, data: ReservationIn) -> Delivery:
        """
        Reserva una taquilla de la talla pedida para el paquete del transportista y crea la entrega en PENDING.
        Todo en una transacción: si algo falla, se deshace todo y la taquilla vuelve a quedar libre
        """

        # La transacción es lo primero del caso de uso (I5): al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            # 1. Comprueba que el edificio existe. Sin esto, un edificio inexistente parecería uno sin taquillas (409)
            if not await self._buildings.exists(data.building_id):
                raise BuildingNotFoundError(data.building_id)

            # 2. Ocupa una taquilla libre de esa talla, en una sola sentencia. Si no queda ninguna, 409.
            # Va antes que crear la entrega: un paquete duplicado sin taquillas libres recibe este error (A10)
            locker = await self._lockers.allocate(data.building_id, data.size)
            if locker is None:
                raise NoLockerAvailableError

            # 3. Crea la entrega en la taquilla asignada
            return await self._deliveries.add(locker, carrier, data)
