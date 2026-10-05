# Modelos de datos para la base de datos de entregas.
# Son clases de SQLAlchemy: describen cómo se guardan los datos, no lo que ve la API
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from locker.core.database import Base

# Condición de «entrega activa»: la que todavía ocupa su taquilla. Una entrega recogida ya no cuenta
ACTIVE = text("status IN ('PENDING', 'DEPOSITED')")


class DeliveryModel(Base):
    """Clase que representa una entrega (la reserva de una taquilla para un paquete) en la base de datos."""

    # Nombre de la tabla en Postgres
    __tablename__ = "deliveries"

    # Restricciones de la tabla.
    # Estados válidos de una entrega
    # Índice único parcial: una taquilla nunca tiene dos entregas activas (I1)
    # Índice único parcial: un paquete (transportista + referencia) nunca tiene dos entregas activas (I2).
    # Son parciales (solo las filas activas) para que las entregas ya recogidas no impidan reutilizar la taquilla
    # ni volver a enviar el mismo paquete
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'DEPOSITED', 'PICKED_UP')", name="status"),
        Index("uq_deliveries_active_locker", "locker_id", unique=True, postgresql_where=ACTIVE),
        Index("uq_deliveries_active_package", "carrier", "tracking_ref", unique=True, postgresql_where=ACTIVE),
    )

    # Columnas de la tabla.
    # id: UUID v7 generado en la aplicación al crear la fila
    # locker_id: FK hacia lockers.id: fk_deliveries_locker_id_lockers
    # carrier: String de hasta 100 caracteres, NOT NULL. Nombre del transportista, sale de su clave de API
    # tracking_ref: String de hasta 64 caracteres, NOT NULL. Referencia del paquete
    # recipient: String de hasta 255 caracteres, NOT NULL. A quién se avisa (texto libre)
    # status: String de 10 caracteres, NOT NULL. PENDING, DEPOSITED o PICKED_UP. El valor por defecto lo pone la BD
    # deposited_at y picked_up_at: fecha con zona horaria, NULL hasta que se deposita o se recoge
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    locker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lockers.id"))
    carrier: Mapped[str] = mapped_column(String(100))
    tracking_ref: Mapped[str] = mapped_column(String(64))
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), server_default="PENDING")
    deposited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
