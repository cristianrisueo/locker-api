# Modelos de datos para la base de datos de edificios.
# Son clases de SQLAlchemy: describen cómo se guardan los datos, no lo que ve la API
import uuid

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from locker.core.database import Base


class BuildingModel(Base):
    """Clase que representa un edificio en la base de datos."""

    # Nombre de la tabla en Postgres
    __tablename__ = "buildings"

    # Restricciones de la tabla.
    # Formato del país: dos letras mayúsculas (ck_buildings_country_format). Pydantic ya lo valida en la API,
    # pero así la tabla se protege aunque alguien escriba en ella por otro camino
    __table_args__ = (CheckConstraint("country ~ '^[A-Z]{2}$'", name="country_format"),)

    # Columnas de la tabla.
    # id: UUID v7 generado en la aplicación al crear la fila: lleva la hora dentro, así que no hace falta created_at
    # name: String de hasta 100 caracteres, NOT NULL
    # country: String de 2 caracteres, NOT NULL. Código del país. Se añadió con una migración con datos (§5.8)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2))
