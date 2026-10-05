# Rutas de la API de edificios.
from fastapi import APIRouter, Depends, status

from locker.buildings.schemas import Building, BuildingIn
from locker.core.security import require_role

# Prefijo de la ruta y etiqueta para la documentación de Swagger. main.py añade delante /v1
router = APIRouter(prefix="/buildings", tags=["buildings"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Crear un edificio",
    dependencies=[Depends(require_role("operator"))],
)
async def create_building(body: BuildingIn) -> Building:
    """Crea un edificio (solo el operador) y lo devuelve con su identificador."""
    raise NotImplementedError
