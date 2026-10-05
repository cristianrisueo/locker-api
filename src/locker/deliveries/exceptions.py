# Errores de dominio de entregas. Solo heredan de la familia que les corresponde.
from locker.core.exceptions import ConflictError


class DuplicatePackageError(ConflictError):
    """El paquete (transportista + referencia) ya tiene una entrega activa."""

    code = "DUPLICATE_PACKAGE"

    def __init__(self) -> None:
        super().__init__("Este paquete ya tiene una reserva activa")
