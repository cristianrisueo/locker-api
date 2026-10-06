# Caducidad de reservas: una reserva que no se deposita a tiempo pasa a EXPIRED y libera su taquilla (§7.13).
# La usa el worker (outbox/worker.py), un proceso aparte con el mismo código que la API.
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.repository import DeliveryRepository
from locker.lockers.repository import LockerRepository

# Logger de la caducidad: una línea por reserva caducada, con el id de la entrega. No hay evento ni aviso (A25)
logger = logging.getLogger(__name__)


class ExpirationService:
    def __init__(self, session: AsyncSession, deliveries: DeliveryRepository, lockers: LockerRepository) -> None:
        """
        Recibe una sesión (para abrir la transacción) y los repositorios que la usan: el de entregas y el de taquillas.
        Solo repositorios: un servicio no llama a servicios de otros dominios (§9.2)
        """
        self._session = session
        self._deliveries = deliveries
        self._lockers = lockers

    async def expire_next(self) -> bool:
        """
        Caduca la siguiente reserva vencida (§7.13), en una transacción corta: la pasa a EXPIRED y libera su taquilla.
        Las dos cosas van juntas (I14): nunca queda una entrega EXPIRED con su taquilla BUSY.
        Devuelve False si no había ninguna reserva vencida que caducar, y True si ha caducado una
        """

        # Crea la transacción: al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            # 1. Pasa a EXPIRED la reserva vencida más antigua que no tenga otra transacción, en una sola sentencia.
            # Si un depósito de esa misma reserva gana la carrera, aquí no se encuentra: ya no está PENDING
            expired = await self._deliveries.expire_due()
            if expired is None:
                return False

            # 2. Libera su taquilla, también condicional (BUSY -> FREE). Una reserva PENDING siempre ocupa su taquilla:
            # si no estaba ocupada, algo va muy mal, y el error deshace también la caducidad
            if not await self._lockers.release(expired.locker_id):
                raise RuntimeError(f"La taquilla {expired.locker_id} de una reserva caducada no estaba ocupada")

            # 3. Lo deja en el log: es el único rastro de la caducidad, aparte del estado de la entrega
            logger.info("Reserva caducada: su taquilla queda libre", extra={"delivery_id": str(expired.delivery_id)})
            return True
