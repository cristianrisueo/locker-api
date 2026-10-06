# Caducidad de reservas: una reserva que no se deposita a tiempo pasa a EXPIRED y libera su taquilla (§7.13).
# La usa el worker (outbox/worker.py), un proceso aparte con el mismo código que la API.
from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.repository import DeliveryRepository
from locker.lockers.repository import LockerRepository


class ExpirationService:
    def __init__(self, session: AsyncSession, deliveries: DeliveryRepository, lockers: LockerRepository) -> None:
        """Recibe una sesión (para abrir la transacción) y los repositorios que la usan: el de entregas y el de taquillas."""
        self._session = session
        self._deliveries = deliveries
        self._lockers = lockers

    async def expire_next(self) -> bool:
        """Caduca la siguiente reserva vencida. Devuelve False si no había ninguna."""
        raise NotImplementedError
