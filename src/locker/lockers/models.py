# Modelos de datos para la base de datos de taquillas.
# Son clases de SQLAlchemy: describen cómo se guardan los datos, no lo que ve la API
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from locker.core.database import Base


class LockerModel(Base):
    """Clase que representa una taquilla de un edificio en la base de datos."""

    # Nombre de la tabla en Postgres
    __tablename__ = "lockers"

    # Restricciones de la tabla.
    # Unicidad: Una etiqueta no se repite dentro de un edificio
    # Tallas y estados válidos
    # Índice parcial (que cumplen la condición): taquillas libres, por edificio y talla. Lo que necesita una reserva
    __table_args__ = (
        UniqueConstraint("building_id", "label", name="uq_lockers_building_id_label"),
        CheckConstraint("size IN ('S', 'M', 'L')", name="size"),
        CheckConstraint("status IN ('FREE', 'BUSY')", name="status"),
        Index("ix_lockers_free_by_size", "building_id", "size", postgresql_where=text("status = 'FREE'")),
    )

    # Columnas de la tabla.
    # id: UUID v7 generado en la aplicación al crear la fila: lleva la hora dentro, así que no hace falta created_at
    # building_id: FK hacia buildings.id: fk_lockers_building_id_buildings.
    # label: String de hasta 10 caracteres, NOT NULL.
    # size: String de 1 carácter, NOT NULL. S, M o L.
    # status: String de 4 caracteres, NOT NULL. FREE o BUSY. El valor por defecto lo pone la base de datos
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    building_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buildings.id"))
    label: Mapped[str] = mapped_column(String(10))
    size: Mapped[str] = mapped_column(String(1))
    status: Mapped[str] = mapped_column(String(4), server_default="FREE")
