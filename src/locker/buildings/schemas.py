# Modelos de datos para la API de edificios.
import uuid

from pydantic import BaseModel, ConfigDict, Field


class BuildingIn(BaseModel):
    """Datos necesarios para crear un edificio."""

    # Quita los espacios sobrantes de los extremos
    model_config = ConfigDict(str_strip_whitespace=True)

    # El nombre no puede quedar vacío tras quitar los espacios.
    name: str = Field(min_length=1, max_length=100, description="Nombre del edificio", examples=["Edificio Sol"])


class Building(BaseModel):
    """Edificio almacenado."""

    id: uuid.UUID
    name: str
