# Rutas de la API de taquillas: alta de taquillas y capacidad, colgadas de su edificio.
import uuid

from fastapi import APIRouter, Depends, status

from locker.core.security import require_role
from locker.lockers.schemas import Capacity, LockersCreated, LockersIn

# Prefijo de la ruta y etiqueta para la documentación de Swagger. main.py añade delante /v1
router = APIRouter(prefix="/buildings/{building_id}", tags=["lockers"])


@router.post(
    "/lockers",
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta taquillas",
    dependencies=[Depends(require_role("operator"))],
)
async def create_lockers(building_id: uuid.UUID, body: LockersIn) -> LockersCreated:
    """Da de alta taquillas de una talla (solo el operador), con etiquetas consecutivas por talla."""
    raise NotImplementedError


@router.get(
    "/capacity",
    summary="Consultar la capacidad",
    dependencies=[Depends(require_role("operator", "carrier"))],
)
async def get_capacity(building_id: uuid.UUID) -> Capacity:
    """Devuelve cuántas taquillas hay y cuántas están libres, por talla."""
    raise NotImplementedError
