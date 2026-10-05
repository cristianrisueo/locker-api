# Modelos de datos para la base de datos del outbox: los eventos pendientes de enviar.
# Son clases de SQLAlchemy: describen cómo se guardan los datos, no lo que ve la API
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from locker.core.database import Base


class OutboxEventModel(Base):
    """
    Clase que representa un evento pendiente de enviar en la base de datos.
    Se escribe en la misma transacción que el cambio que lo provoca, y el worker lo envía después.
    Sin índices: las filas enviadas se borran, así que la tabla solo contiene eventos pendientes y muertos
    """

    # Nombre de la tabla en Postgres
    __tablename__ = "outbox_events"

    # Columnas de la tabla.
    # id: UUID v7 generado en la aplicación. Es el event_id con el que el receptor reconoce un aviso repetido
    # type: String de hasta 100 caracteres, NOT NULL. Qué ha pasado (hoy solo delivery.deposited)
    # payload: JSONB, NOT NULL. Los datos del evento (hoy solo el id de la entrega)
    # attempts: entero, NOT NULL, 0 por defecto. Intentos de envío fallidos
    # next_attempt_at: fecha con zona horaria; por defecto now(), así que el evento se puede enviar ya.
    # NULL significa evento muerto: agotó sus intentos y el worker ya no lo toma
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
