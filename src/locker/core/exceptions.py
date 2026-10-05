# Errores de negocio, compartidos por todos los dominios.
# Cada dominio hereda de la familia que le corresponde; ninguno sabe nada de HTTP.
from typing import ClassVar


class DomainError(Exception):
    """Base de todos los errores de negocio de la aplicación."""

    code: ClassVar[str]

    def __init__(self, detail: str) -> None:
        raise NotImplementedError


class NotFoundError(DomainError):
    """El recurso pedido no existe."""


class ConflictError(DomainError):
    """La operación choca con el estado actual (por ejemplo, un duplicado)."""


class ForbiddenError(DomainError):
    """Quien llama está identificado, pero no puede hacer esta operación."""


class UnauthenticatedError(DomainError):
    """Quien llama no se ha identificado, o su identificación no es válida."""


class UnprocessableError(DomainError):
    """La petición está bien formada, pero no se puede procesar."""


class ServiceUnavailableError(DomainError):
    """Un sistema del que depende la aplicación (la base de datos) no responde."""
