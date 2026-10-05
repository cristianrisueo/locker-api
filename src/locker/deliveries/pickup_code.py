# Código de recogida: se calcula a partir del secreto del servidor y del id de la entrega, y no se guarda.
import uuid


def derive(secret: str, delivery_id: uuid.UUID) -> str:
    """Código de recogida de la entrega: seis cifras."""
    raise NotImplementedError


def matches(secret: str, delivery_id: uuid.UUID, candidate: str) -> bool:
    """Si el código recibido es el de la entrega."""
    raise NotImplementedError
