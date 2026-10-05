# Modelos de datos para la base de datos de claves de idempotencia.
# Son clases de SQLAlchemy: describen cómo se guardan los datos, no lo que ve la API
from typing import Any

from sqlalchemy import PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from locker.core.database import Base


class IdempotencyKeyModel(Base):
    """Clase que representa una clave de idempotencia de una reserva, con la respuesta que se dio, en la base de datos."""

    # Nombre de la tabla en Postgres
    __tablename__ = "idempotency_keys"

    # Restricciones de la tabla.
    # PK compuesta (carrier, key): la clave es por transportista, así que dos transportistas pueden usar la misma.
    # Es la restricción que hace esperar a una segunda petición con la misma clave (INSERT ... ON CONFLICT).
    # Lleva nombre explícito porque la convención de nombres no cubre las PK
    __table_args__ = (PrimaryKeyConstraint("carrier", "key", name="pk_idempotency_keys"),)

    # Columnas de la tabla.
    # carrier: String de hasta 100 caracteres, NOT NULL. Transportista dueño de la clave, sale de su clave de API
    # key: String de hasta 255 caracteres, NOT NULL. Valor de la cabecera Idempotency-Key
    # request_hash: String de 64 caracteres, NOT NULL. Huella del cuerpo (SHA-256 en hexadecimal)
    # response_body: JSONB. La respuesta de la reserva. NULL solo mientras dura su transacción: se rellena antes
    # de confirmar. Sin FK a deliveries: la respuesta guardada ya lleva el id de la entrega
    carrier: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
