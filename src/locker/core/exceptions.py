# Errores de negocio, compartidos por todos los dominios.
# Cada dominio hereda de la familia que le corresponde; ninguno sabe nada de HTTP.
# El código HTTP de cada familia lo decide core/exception_handlers.py; aquí solo vive el code del catálogo (§8.3).
from typing import ClassVar


class DomainError(Exception):
    """
    Base de todos los errores de negocio de la aplicación.
    code: identificador estable para el cliente (catálogo cerrado de §8.3). Lo fija cada familia o cada error.
    detail: mensaje legible para el cliente, en castellano.
    """

    code: ClassVar[str]

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    """El recurso pedido no existe."""

    code = "NOT_FOUND"


class ConflictError(DomainError):
    """
    La operación choca con el estado actual (por ejemplo, un duplicado).
    Sin code propio: el catálogo no tiene uno genérico de conflicto, cada error pone el suyo (DUPLICATE_PACKAGE...)
    """


class ForbiddenError(DomainError):
    """Quien llama está identificado, pero no puede hacer esta operación."""

    code = "FORBIDDEN"


class UnauthenticatedError(DomainError):
    """Quien llama no se ha identificado, o su identificación no es válida."""

    code = "UNAUTHENTICATED"


class UnprocessableError(DomainError):
    """
    La petición está bien formada, pero no se puede procesar.
    Sin code propio: VALIDATION_ERROR lo pone FastAPI; los errores de dominio ponen el suyo (IDEMPOTENCY_KEY_REUSED)
    """


class ServiceUnavailableError(DomainError):
    """Un sistema del que depende la aplicación (la base de datos) no responde."""

    code = "SERVICE_UNAVAILABLE"
