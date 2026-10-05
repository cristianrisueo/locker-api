# Capa de servicio del outbox: enviar el aviso de un evento pendiente y, si falla, programar el reintento.
# Lo usa el worker (worker.py), un proceso aparte con el mismo código que la API.
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from locker.core.config import Settings
from locker.deliveries import pickup_code
from locker.deliveries.repository import DeliveryRepository
from locker.outbox.events import DELIVERY_DEPOSITED
from locker.outbox.notifier import MESSAGE, Notification, Notifier
from locker.outbox.repository import OutboxEvent, OutboxRepository

# Logger de los fallos de envío. Registra el id del evento y el error, nunca el aviso: el código no sale de aquí (I7)
logger = logging.getLogger(__name__)


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
        """
        Recibe una sesión (para abrir la transacción), los repositorios que la usan (el del outbox y el de entregas),
        el notificador que envía el aviso y la configuración: el secreto del código y las reglas de reintento
        """
        self._session = session
        self._outbox = outbox
        self._deliveries = deliveries
        self._notifier = notifier
        self._settings = settings

    async def process_next(self) -> bool:
        """
        Procesa el siguiente evento vencido (§7.10), todo en una transacción: lo toma, construye el aviso, lo envía
        y borra el evento. Si algo falla al construir o enviar el aviso, apunta el fallo en vez de borrarlo.
        Devuelve False si no había ningún evento que procesar, y True si ha procesado uno (enviado o fallido).
        La transacción queda abierta mientras se envía el aviso (A3): así el evento sigue bloqueado y ningún otro
        worker lo envía a la vez
        """

        # Crea la transacción: al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            # 1. Toma el evento vencido más antiguo que no tenga otro worker. Si no hay ninguno, no hay nada que hacer
            event = await self._outbox.take_due()
            if event is None:
                return False

            # 2. Construye el aviso y se lo pasa al notificador
            try:
                notification = await self._build_notification(event)
                await self._notifier.send(notification)

            # 3a. Ha fallado: apunta el fallo y NO relanza el error. Si lo relanzara, la transacción se desharía y el
            # fallo no quedaría apuntado: el evento seguiría vencido con los mismos intentos y se reintentaría sin
            # fin, sin espera y sin llegar nunca a muerto
            except Exception as exc:
                await self._record_failure(event, exc)

            # 3b. Enviado: borra el evento
            else:
                await self._outbox.delete(event.id)

            # Al salir del bloque se confirma la transacción: el borrado o el fallo apuntado
            return True

    async def _record_failure(self, event: OutboxEvent, exc: Exception) -> None:
        """
        Apunta un envío fallido: suma un intento y, si aún le quedan, programa el reintento tras la espera que toca;
        si los ha agotado, deja el evento muerto. Lo registra en el log con el id del evento y el error
        """

        # El nuevo número de fallos. La fila está bloqueada desde take_due: nadie más la ha cambiado entretanto
        attempts = event.attempts + 1

        # Muerto (sin espera) o vivo con la espera que corresponde a este fallo
        dead = is_dead(attempts, self._settings.outbox_max_attempts)
        retry_in = None if dead else retry_delay_seconds(attempts, self._settings.outbox_backoff_base_seconds)

        # Solo el id del evento, los intentos y el tipo y texto del error: nunca el aviso, que lleva el código
        logger.warning(
            "Aviso no enviado: el evento queda muerto" if dead else "Aviso no enviado: se reintentará",
            extra={"event_id": str(event.id), "attempts": attempts, "error": f"{type(exc).__name__}: {exc}"},
        )
        await self._outbox.record_failure(event.id, attempts, retry_in)

    async def _build_notification(self, event: OutboxEvent) -> Notification:
        """
        Construye el aviso del evento. El evento solo lleva el id de la entrega (I7): el destinatario, la taquilla y el
        edificio se leen ahora, y el código se calcula con el secreto, como al recoger. Lanza un error si el evento
        no es de un tipo conocido o si su entrega no existe
        """

        # Hoy solo hay un tipo de evento: cualquier otro no se sabría avisar
        if event.type != DELIVERY_DEPOSITED:
            raise ValueError(f"Tipo de evento desconocido: {event.type}")

        # Lee los datos de la entrega. Si ya no existe, no hay a quién avisar
        delivery_id = uuid.UUID(event.payload["delivery_id"])
        notice = await self._deliveries.get_notice(delivery_id)
        if notice is None:
            raise LookupError(f"La entrega {delivery_id} no existe")

        # Calcula el código de recogida, el mismo que comprobará la recogida, y escribe el texto del aviso
        code = pickup_code.derive(self._settings.pickup_code_secret.get_secret_value(), delivery_id)
        return Notification(
            event_id=event.id,
            delivery_id=delivery_id,
            recipient=notice.recipient,
            building_name=notice.building_name,
            locker_label=notice.locker_label,
            pickup_code=code,
            message=MESSAGE.format(label=notice.locker_label, building=notice.building_name, code=code),
        )
