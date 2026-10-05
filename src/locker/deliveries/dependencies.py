# Construye las dependencias de la capa de entregas. Se usa en las rutas para inyectar el servicio.
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.dependencies import get_repository as get_building_repository
from locker.buildings.repository import BuildingRepository
from locker.core.database import get_session
from locker.deliveries.repository import DeliveryRepository, SqlDeliveryRepository
from locker.deliveries.service import DeliveryService
from locker.idempotency.dependencies import get_repository as get_idempotency_repository
from locker.idempotency.repository import IdempotencyRepository
from locker.lockers.dependencies import get_repository as get_locker_repository
from locker.lockers.repository import LockerRepository
from locker.outbox.repository import OutboxRepository, SqlOutboxRepository


def get_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> DeliveryRepository:
    """Construye el repositorio con la sesión de la petición actual."""
    return SqlDeliveryRepository(session)


def get_outbox_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> OutboxRepository:
    """
    Construye el repositorio del outbox con la sesión de la petición. Se construye aquí porque outbox no expone
    endpoints ni tiene dependencies.py: el único que lo usa desde la API es el servicio de entregas
    """
    return SqlOutboxRepository(session)


def get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    deliveries: Annotated[DeliveryRepository, Depends(get_repository)],
    lockers: Annotated[LockerRepository, Depends(get_locker_repository)],
    buildings: Annotated[BuildingRepository, Depends(get_building_repository)],
    idempotency: Annotated[IdempotencyRepository, Depends(get_idempotency_repository)],
    outbox: Annotated[OutboxRepository, Depends(get_outbox_repository)],
) -> DeliveryService:
    """Construye el servicio con sus cinco repositorios. Todos comparten la sesión de la petición."""
    return DeliveryService(session, deliveries, lockers, buildings, idempotency, outbox)


# Atajo para reutilizar en las rutas: inyecta el servicio de entregas ya construido
DeliveryServiceDep = Annotated[DeliveryService, Depends(get_service)]
