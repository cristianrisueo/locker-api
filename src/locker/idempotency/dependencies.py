# Construye las dependencias de la capa de idempotencia. No tiene servicio: su repositorio lo usa el de entregas.
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from locker.core.database import get_session
from locker.idempotency.repository import IdempotencyRepository, SqlIdempotencyRepository


def get_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> IdempotencyRepository:
    """Construye el repositorio con la sesión de la petición actual."""
    return SqlIdempotencyRepository(session)
