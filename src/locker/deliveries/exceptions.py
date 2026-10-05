# Errores de dominio de entregas. Solo heredan de la familia que les corresponde.
import uuid

from locker.core.exceptions import ConflictError, NotFoundError


class DuplicatePackageError(ConflictError):
    """El paquete (transportista + referencia) ya tiene una entrega activa."""

    code = "DUPLICATE_PACKAGE"

    def __init__(self) -> None:
        super().__init__("Este paquete ya tiene una reserva activa")


class DeliveryNotFoundError(NotFoundError):
    """
    La entrega pedida no existe. También cuando es de otro transportista: así no se revela que existe (D11)
    """

    def __init__(self, delivery_id: uuid.UUID) -> None:
        super().__init__(f"Entrega {delivery_id} no encontrada")
        self.delivery_id = delivery_id


class InvalidStateError(ConflictError):
    """La entrega no está en el estado que pide la operación (por ejemplo, depositar una entrega ya recogida)."""

    code = "INVALID_STATE"

    def __init__(self) -> None:
        super().__init__("La entrega no está en un estado que permita esta operación")
