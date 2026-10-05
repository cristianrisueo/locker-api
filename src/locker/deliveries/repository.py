# Repositorio de entregas: define la interfaz y su implementación sobre PostgreSQL.
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


def is_violation_of(error: IntegrityError, sqlstate: str, constraint: str) -> bool:
    """
    Dice si el IntegrityError es la violación de esa restricción concreta.
    error.orig es el error del driver adaptado por SQLAlchemy (lleva el sqlstate) y su causa es la
    excepción original de asyncpg (lleva constraint_name)
    """
    original = error.orig
    return (
        getattr(original, "sqlstate", None) == sqlstate
        and getattr(original.__cause__ if original else None, "constraint_name", None) == constraint
    )


class DeliveryRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Crea una entrega PENDING en la taquilla asignada y la devuelve completa.
    # Si el paquete ya tiene una entrega activa, lanza DuplicatePackageError
    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery: ...


class SqlDeliveryRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery:
        """
        Inserta la entrega en la taquilla asignada y la devuelve con los datos de esa taquilla.
        No se comprueba antes con un SELECT si el paquete ya tiene una entrega activa (I2): lo impide el índice
        uq_deliveries_active_package, y aquí solo se traduce su error
        """

        # INSERT ... RETURNING: devuelve la fila completa, también el estado PENDING que pone la base de datos.
        # El id (UUID v7) lo genera la aplicación
        stmt = (
            insert(DeliveryModel)
            .values(locker_id=locker.id, carrier=carrier, tracking_ref=data.tracking_ref, recipient=data.recipient)
            .returning(DeliveryModel)
        )
        try:
            model = (await self._session.scalars(stmt)).one()
        except IntegrityError as exc:
            # Solo se traduce la violación del índice de paquete activo. Cualquier otra se relanza tal cual.
            # Sin rollback: la transacción es del servicio, y el error al salir de su bloque begin() la deshace
            # entera (también la taquilla que se acababa de ocupar)
            if is_violation_of(exc, UNIQUE_VIOLATION, "uq_deliveries_active_package"):
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
