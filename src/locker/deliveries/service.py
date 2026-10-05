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
        raise NotImplementedError
