# Construye las dependencias de la capa de taquillas. Se usa en las rutas para inyectar el servicio.
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.dependencies import get_repository as get_building_repository
from locker.buildings.repository import BuildingRepository
from locker.core.database import get_session
from locker.lockers.repository import LockerRepository, SqlLockerRepository
from locker.lockers.service import LockerService


def get_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> LockerRepository:
    """Construye el repositorio con la sesión de la petición actual."""
    return SqlLockerRepository(session)


def get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    lockers: Annotated[LockerRepository, Depends(get_repository)],
    buildings: Annotated[BuildingRepository, Depends(get_building_repository)],
) -> LockerService:
    """Construye el servicio con sus dos repositorios. Todos comparten la sesión de la petición."""
    return LockerService(session, lockers, buildings)


# Atajo para reutilizar en las rutas: inyecta el servicio de taquillas ya construido
LockerServiceDep = Annotated[LockerService, Depends(get_service)]
