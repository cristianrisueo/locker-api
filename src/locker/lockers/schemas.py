# Modelos de datos para la API de taquillas.
import uuid
from typing import Literal

from pydantic import BaseModel, Field

# Tallas de taquilla, de menor a mayor. La capacidad se devuelve en este orden
type Size = Literal["S", "M", "L"]
SIZES: tuple[Size, ...] = ("S", "M", "L")

# Estados de una taquilla: libre u ocupada por una entrega
type LockerStatus = Literal["FREE", "BUSY"]


class LockersIn(BaseModel):
    """Datos para dar de alta taquillas de una talla en un edificio."""

    size: Size = Field(description="Talla de las taquillas", examples=["M"])
    quantity: int = Field(default=1, ge=1, le=100, description="Cuántas taquillas se dan de alta", examples=[3])


class Locker(BaseModel):
    """Taquilla almacenada, con su etiqueta generada."""

    id: uuid.UUID
    label: str
    size: Size
    status: LockerStatus


class LockersCreated(BaseModel):
    """Respuesta del alta: las taquillas creadas, en orden de etiqueta."""

    lockers: list[Locker]


class SizeCapacity(BaseModel):
    """Capacidad de una talla: cuántas taquillas hay y cuántas están libres."""

    size: Size
    total: int
    free: int


class Capacity(BaseModel):
    """Capacidad de un edificio, desglosada por talla. Solo aparecen las tallas que existen."""

    building_id: uuid.UUID
    sizes: list[SizeCapacity]
