# Rutas de la API de entregas. De momento, solo reservar.
from typing import Annotated

from fastapi import APIRouter, Depends, status

from locker.core.security import Principal, require_role
from locker.deliveries.dependencies import DeliveryServiceDep
from locker.deliveries.schemas import Delivery, ReservationIn

# Prefijo de la ruta y etiqueta para la documentación de Swagger. main.py añade delante /v1
router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Reservar una taquilla",
    responses={
        404: {"description": "El edificio no existe"},
        409: {"description": "No queda taquilla libre de esa talla, o el paquete ya tiene una reserva activa"},
    },
)
async def reserve(
    body: ReservationIn,
    principal: Annotated[Principal, Depends(require_role("carrier"))],
    service: DeliveryServiceDep,
) -> Delivery:
    """
    Reserva una taquilla libre de la talla pedida (solo un transportista) y crea la entrega en PENDING.
    El transportista es el de la clave de API, no un campo del cuerpo
    """

    # Una clave carrier siempre lleva name: lo exige la validación de la configuración al arrancar
    assert principal.name is not None
    return await service.reserve(principal.name, body)
