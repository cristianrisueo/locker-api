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

    __table_args__ = (
        # Una etiqueta no se repite dentro de un edificio. El nombre se da entero: la convención de nombres
        # solo usaría la primera columna (uq_lockers_building_id)
        UniqueConstraint("building_id", "label", name="uq_lockers_building_id_label"),
        # Tallas y estados válidos. Pydantic ya los valida en la API, pero así la tabla se protege aunque alguien
        # escriba en ella por otro camino. La convención de nombres los convierte en ck_lockers_size y ck_lockers_status
        CheckConstraint("size IN ('S', 'M', 'L')", name="size"),
        CheckConstraint("status IN ('FREE', 'BUSY')", name="status"),
        # Índice PARCIAL: solo guarda las taquillas libres, por edificio y talla. Es justo lo que busca la reserva
        # («una taquilla FREE de esta talla en este edificio»), y no crece con las taquillas ocupadas
        Index("ix_lockers_free_by_size", "building_id", "size", postgresql_where=text("status = 'FREE'")),
    )

    # Columnas de la tabla.
    # UUID v7 generado en la aplicación al crear la fila
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # FK hacia buildings.id: fk_lockers_building_id_buildings. Sin índice propio: lo cubre la restricción única,
    # que empieza por building_id
    building_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buildings.id"))
    label: Mapped[str] = mapped_column(String(10))  # Etiqueta generada, <talla>-<nn>: M-03, NOT NULL
    size: Mapped[str] = mapped_column(String(1))  # S, M o L, NOT NULL
    # FREE o BUSY, NOT NULL. El valor por defecto lo pone la base de datos, así vale también para un INSERT en SQL
    status: Mapped[str] = mapped_column(String(4), server_default="FREE")
