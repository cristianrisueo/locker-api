# NotificadorFalso: el único doble de prueba del proyecto (§14.3), para provocar fallos al enviar un aviso.
from typing import Literal

from locker.outbox.notifier import Notification


class EnvioFallido(Exception):
    """El fallo que lanza NotificadorFalso cuando se le pide: el aviso no ha llegado al residente."""


class NotificadorFalso:
    """
    Existe porque un fallo del sistema que envía el aviso no se puede provocar de verdad.
    Implementa Notifier, graba cada aviso que recibe en recibidas y falla cuando se le configura con fallar:
    "antes" lanza EnvioFallido sin grabar (el aviso no sale) y "despues" graba y luego lo lanza (el aviso sale,
    pero quien lo envía no se entera). Con None, envía sin fallar
    """

    def __init__(self) -> None:
        self.recibidas: list[Notification] = []
        self.fallar: Literal["antes", "despues"] | None = None

    async def send(self, notification: Notification) -> None:
        if self.fallar == "antes":
            raise EnvioFallido("fallo provocado al enviar el aviso")
        self.recibidas.append(notification)
        if self.fallar == "despues":
            raise EnvioFallido("fallo provocado tras enviar el aviso")
