# Rutas de la API de entregas: reservar y depositar.
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

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
        422: {"description": "Datos mal formados, falta Idempotency-Key, o la clave ya se usó con otro cuerpo"},
    },
)
async def reserve(
    body: ReservationIn,
    principal: Annotated[Principal, Depends(require_role("carrier"))],
    service: DeliveryServiceDep,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            description="Identifica la petición: repetirla con la misma clave devuelve la misma respuesta",
        ),
    ],
) -> Delivery:
    """
    Reserva una taquilla libre de la talla pedida (solo un transportista) y crea la entrega en PENDING.
    El transportista es el de la clave de API, no un campo del cuerpo.
    La cabecera Idempotency-Key es obligatoria: si falta, FastAPI responde 422 al validarla
    """

    # Una clave carrier siempre lleva name: lo exige la validación de la configuración al arrancar
    assert principal.name is not None
    return await service.reserve(principal.name, idempotency_key, body)


@router.post(
    "/{delivery_id}/deposit",
    summary="Depositar el paquete en su taquilla",
    responses={
        404: {"description": "La entrega no existe o es de otro transportista"},
        409: {"description": "La entrega ya se ha recogido"},
    },
)
async def deposit(
    delivery_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_role("carrier"))],
    service: DeliveryServiceDep,
) -> Delivery:
    """
    El transportista dueño de la entrega deposita el paquete: la entrega pasa a DEPOSITED y se avisará al residente.
    Sin cuerpo. Depositar otra vez una entrega ya depositada responde 200 con la entrega tal cual
    """

    # Una clave carrier siempre lleva name: lo exige la validación de la configuración al arrancar
    assert principal.name is not None
    return await service.deposit(principal.name, delivery_id)
