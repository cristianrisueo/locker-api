# Repositorio de entregas: define la interfaz y su implementación sobre PostgreSQL.
import uuid
from typing import Protocol

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.exceptions import DuplicatePackageError
from locker.deliveries.models import DeliveryModel
from locker.deliveries.schemas import Delivery, ReservationIn
from locker.lockers.schemas import Locker

# Código SQLSTATE de PostgreSQL para una fila que incumple una restricción de unicidad
UNIQUE_VIOLATION = "23505"


class DeliveryRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Crea una entrega PENDING en la taquilla asignada y la devuelve completa.
    # Si el paquete ya tiene una entrega activa, lanza DuplicatePackageError
    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery: ...

    # Lee la entrega con los datos de su taquilla. Con carrier, solo si es de ese transportista. None si no la encuentra
    async def get(self, delivery_id: uuid.UUID, carrier: str | None = None) -> Delivery | None: ...

    # Pasa la entrega del transportista de PENDING a DEPOSITED y la devuelve. None si no ha cambiado ninguna fila
    async def deposit(self, delivery_id: uuid.UUID, carrier: str) -> Delivery | None: ...


class SqlDeliveryRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery:
        """
        Inserta la entrega en la taquilla asignada y la devuelve con los datos de esa taquilla.
        No se comprueba antes con un SELECT si el paquete ya tiene una entrega activa: lo impide el índice
        uq_deliveries_active_package, y aquí solo se traduce su error
        """

        # INSERT ... RETURNING: devuelve la fila completa, también el estado PENDING que pone la base de datos.
        # El id (UUID v7) lo genera la aplicación
        stmt = (
            insert(DeliveryModel)
            .values(locker_id=locker.id, carrier=carrier, tracking_ref=data.tracking_ref, recipient=data.recipient)
            .returning(DeliveryModel)
        )

        # La causa del error de integridad es la que tiene el código SQLSTATE 23505 (violación de unicidad)
        # Si es por el índice uq_deliveries_active_package, se traduce a DuplicatePackageError
        try:
            model = (await self._session.scalars(stmt)).one()
        except IntegrityError as exc:
            causa = exc.orig.__cause__ if exc.orig else None

            if (
                getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION
                and getattr(causa, "constraint_name", None) == "uq_deliveries_active_package"
            ):
                raise DuplicatePackageError from exc

            raise

        # La respuesta junta la fila de la entrega con el edificio, la etiqueta y la talla de su taquilla.
        # Se valida un diccionario: Pydantic comprueba que el estado de la fila es uno de los de DeliveryStatus
        return Delivery.model_validate(
            {
                "id": model.id,
                "status": model.status,
                "building_id": data.building_id,
                "locker_label": locker.label,
                "size": locker.size,
                "carrier": model.carrier,
                "tracking_ref": model.tracking_ref,
                "recipient": model.recipient,
                "deposited_at": model.deposited_at,
                "picked_up_at": model.picked_up_at,
            }
        )

    async def get(self, delivery_id: uuid.UUID, carrier: str | None = None) -> Delivery | None:
        """Lee la entrega, unida a su taquilla."""
        raise NotImplementedError

    async def deposit(self, delivery_id: uuid.UUID, carrier: str) -> Delivery | None:
        """UPDATE condicional de PENDING a DEPOSITED."""
        raise NotImplementedError
