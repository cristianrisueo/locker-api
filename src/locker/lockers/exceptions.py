# Errores de dominio de taquillas. Solo heredan de la familia que les corresponde.
# Un edificio inexistente no está aquí: es BuildingNotFoundError, del dominio de edificios.
from locker.core.exceptions import ConflictError


class NoLockerAvailableError(ConflictError):
    """No queda ninguna taquilla libre de la talla pedida en el edificio."""

    code = "NO_LOCKER_AVAILABLE"

    def __init__(self) -> None:
        super().__init__("No quedan taquillas de esta talla disponibles")
