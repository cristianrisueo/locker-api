# Construye las dependencias de la capa de edificios. Se usa en las rutas para inyectar el servicio.
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.repository import BuildingRepository, SqlBuildingRepository
from locker.buildings.service import BuildingService
from locker.core.database import get_session


def get_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> BuildingRepository:
    """Construye el repositorio con la sesión de la petición actual."""
    return SqlBuildingRepository(session)


def get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    repository: Annotated[BuildingRepository, Depends(get_repository)],
) -> BuildingService:
    """Construye el servicio con la misma sesión que su repositorio: FastAPI da una sola sesión por petición."""
    return BuildingService(session, repository)


# Atajo para reutilizar en las rutas: inyecta el servicio de edificios ya construido
BuildingServiceDep = Annotated[BuildingService, Depends(get_service)]
