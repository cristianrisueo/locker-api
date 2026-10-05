# Capa de servicio de entregas: reservar una taquilla para un paquete.
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.repository import BuildingRepository
from locker.deliveries.repository import DeliveryRepository
from locker.deliveries.schemas import Delivery, ReservationIn
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
            # 1. Ocupa una taquilla libre de esa talla, en una sola sentencia
            locker = await self._lockers.allocate(data.building_id, data.size)
            if locker is None:
                raise NotImplementedError

            # 2. Crea la entrega en la taquilla asignada
            return await self._deliveries.add(locker, carrier, data)
