# Capa de servicio del outbox: enviar el aviso de un evento pendiente y, si falla, programar el reintento.
# Lo usa el worker (worker.py), un proceso aparte con el mismo código que la API.
from sqlalchemy.ext.asyncio import AsyncSession

from locker.core.config import Settings
from locker.deliveries.repository import DeliveryRepository
from locker.outbox.notifier import Notifier
from locker.outbox.repository import OutboxRepository


def retry_delay_seconds(attempts: int, base_seconds: float) -> float:
    """
    Segundos de espera tras el fallo número attempts (el valor de attempts ya incrementado: 1 tras el primer fallo).
    La espera se duplica en cada fallo empezando por la base: base × 2^(attempts − 1). Con la base por defecto (2),
    los fallos 1 a 4 esperan 2, 4, 8 y 16 segundos, unos 30 en total (A11). Con base 0 no se espera nada.
    El exponente es attempts − 1 y no attempts: así el primer fallo espera la base, como dice la secuencia 2, 4, 8 y 16
    """
    return base_seconds * 2.0 ** (attempts - 1)


def is_dead(attempts: int, max_attempts: int) -> bool:
    """
    Si un evento con attempts fallos ha agotado sus intentos: muere al alcanzar el máximo, no antes.
    Un evento muerto se queda en la tabla con next_attempt_at nulo y el worker ya no lo toma
    """
    return attempts >= max_attempts


class OutboxService:
    def __init__(
        self,
        session: AsyncSession,
        outbox: OutboxRepository,
        deliveries: DeliveryRepository,
        notifier: Notifier,
        settings: Settings,
    ) -> None:
        self._session = session
        self._outbox = outbox
        self._deliveries = deliveries
        self._notifier = notifier
        self._settings = settings

    async def process_next(self) -> bool:
        """Procesa el siguiente evento vencido. False si no había ninguno."""
        raise NotImplementedError
