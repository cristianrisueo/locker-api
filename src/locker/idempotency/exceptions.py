# Errores de dominio de idempotencia. Solo heredan de la familia que les corresponde.
from locker.core.exceptions import UnprocessableError


class IdempotencyKeyReusedError(UnprocessableError):
    """La clave ya se usó con una petición de cuerpo distinto."""

    code = "IDEMPOTENCY_KEY_REUSED"

    def __init__(self) -> None:
        super().__init__("La clave ya se usó con otra petición distinta")
