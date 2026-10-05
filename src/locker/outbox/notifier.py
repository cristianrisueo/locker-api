# Notificador: el aviso al residente de que su paquete está en la taquilla, y quien lo envía.
# La única implementación de producción escribe el aviso en el log (A5): no hay envíos reales.
import logging
import uuid
from dataclasses import dataclass, field
from typing import Protocol

# Logger del notificador de log: su línea es la única del sistema que lleva el código de recogida (I7, A5)
logger = logging.getLogger("locker.notifier")

# Texto del aviso que recibe el residente
MESSAGE = "Tu paquete está en la taquilla {label} del edificio {building}. Tu código de recogida es {code}."


@dataclass(frozen=True)
class Notification:
    """
    Un aviso listo para enviar. event_id es el id del evento del outbox: si el aviso se reenvía, llega con el
    mismo, y el receptor puede ignorar el repetido.
    pickup_code y message (que también lleva el código) van con repr=False: si alguien imprime o registra el aviso
    por error, el código no aparece
    """

    event_id: uuid.UUID
    delivery_id: uuid.UUID
    recipient: str
    building_name: str
    locker_label: str
    pickup_code: str = field(repr=False)
    message: str = field(repr=False)


class Notifier(Protocol):
    """Interfaz del notificador. Cualquier clase con este método la cumple; si no puede enviar, lanza una excepción."""

    async def send(self, notification: Notification) -> None: ...


class LogNotifier:
    """Notificador de demostración: escribe el aviso en el log, en una línea, con event_id y delivery_id como campos."""

    async def send(self, notification: Notification) -> None:
        """Escribe el texto del aviso. Es la única línea de log que contiene el código de recogida (A5)."""
        logger.info(
            notification.message,
            extra={"event_id": str(notification.event_id), "delivery_id": str(notification.delivery_id)},
        )
