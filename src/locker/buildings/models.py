# Modelos de datos para la base de datos de edificios.
# Son clases de SQLAlchemy: describen cómo se guardan los datos, no lo que ve la API
import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from locker.core.database import Base


class BuildingModel(Base):
    """Clase que representa un edificio en la base de datos."""

    # Nombre de la tabla en Postgres
    __tablename__ = "buildings"

    # Columnas de la tabla.
    # UUID v7 generado en la aplicación al crear la fila: lleva la hora dentro, así que no hace falta created_at
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(String(100))  # String de hasta 100 caracteres, NOT NULL. Sin unicidad (A13)
