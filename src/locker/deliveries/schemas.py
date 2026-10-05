# Modelos de datos para la API de entregas.
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from locker.lockers.schemas import Size

# Estados de una entrega: reservada, depositada en la taquilla o recogida por el residente
type DeliveryStatus = Literal["PENDING", "DEPOSITED", "PICKED_UP"]


class ReservationIn(BaseModel):
    """Datos para reservar una taquilla. El transportista no va aquí: sale de su clave de API."""

    # Rechaza campos desconocidos (por ejemplo, un carrier en el cuerpo) y quita los espacios sobrantes de los extremos
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    building_id: uuid.UUID = Field(description="Edificio donde se reserva")
    size: Size = Field(description="Talla de taquilla que se necesita", examples=["M"])
    tracking_ref: str = Field(min_length=1, max_length=64, description="Referencia del paquete", examples=["ES123"])
    recipient: str = Field(
        min_length=1,
        max_length=255,
        description="A quién se avisa: un correo o un teléfono",
        examples=["vecino@example.com"],
    )


class Delivery(BaseModel):
    """Entrega: la reserva de una taquilla para un paquete, con los datos de la taquilla asignada."""

    id: uuid.UUID
    status: DeliveryStatus
    building_id: uuid.UUID
    locker_label: str
    size: Size
    carrier: str
    tracking_ref: str
    recipient: str
    deposited_at: datetime | None
    picked_up_at: datetime | None
