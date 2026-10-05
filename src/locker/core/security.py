# Seguridad: autenticación por clave de API y comprobación de roles.
# La clave llega en la cabecera X-API-Key y se compara con las de la configuración: nunca se consulta la base de datos.
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from locker.core.config import Role, Settings, get_settings

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
    """Dependencia de FastAPI: identifica a quien llama por su clave de API."""
    raise NotImplementedError


def require_role(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Construye una dependencia que deja pasar solo a los roles indicados."""

    async def check_role(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        raise NotImplementedError

    return check_role
