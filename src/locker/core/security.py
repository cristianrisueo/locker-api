# Seguridad: autenticación por clave de API y comprobación de roles.
# La clave llega en la cabecera X-API-Key y se compara con las de la configuración: nunca se consulta la base de datos.
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from locker.core.config import ApiKey, Role, Settings, get_settings
from locker.core.exceptions import ForbiddenError, UnauthenticatedError

# Declara la cabecera X-API-Key (así aparece en la documentación de Swagger).
# auto_error=False: si falta, FastAPI no responde con su propio error; lo decide get_principal con el formato común
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class Principal:
    """Quién llama: su rol y, si es transportista, su nombre. Nunca lleva la clave."""

    role: Role
    name: str | None


async def get_principal(
    api_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """
    Dependencia de FastAPI: identifica a quien llama por su clave de API.
    Falta la clave o no está en la configuración -> 401. El error nunca repite la clave recibida (I9)
    """
    # Sin cabecera (o vacía), APIKeyHeader devuelve None
    if not api_key:
        raise UnauthenticatedError("Falta la clave de API o no es válida")

    # Compara con TODAS las claves, sin parar en la primera que coincida, y cada comparación en tiempo constante
    # (hmac.compare_digest). Así el tiempo de respuesta no revela cuántos caracteres se acertaron ni en qué
    # posición de la lista está la clave. Se comparan bytes: compare_digest no admite textos con caracteres no ASCII
    received = api_key.encode()
    found: ApiKey | None = None
    for entry in settings.api_keys:
        if hmac.compare_digest(entry.key.get_secret_value().encode(), received):
            found = entry

    if found is None:
        raise UnauthenticatedError("Falta la clave de API o no es válida")

    return Principal(role=found.role, name=found.name)


def require_role(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """
    Construye una dependencia que deja pasar solo a los roles indicados.
    Uso en una ruta: Depends(require_role("operator")). Primero identifica (401) y después comprueba el rol (403)
    """

    async def check_role(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        # La clave es válida, pero su rol no permite esta operación
        if principal.role not in roles:
            raise ForbiddenError("Esta clave no tiene permiso para esta operación")
        return principal

    return check_role
