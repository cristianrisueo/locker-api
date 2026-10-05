# Repositorio de entregas: define la interfaz y su implementación sobre PostgreSQL.
import uuid
from typing import NamedTuple, Protocol

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.models import BuildingModel
from locker.deliveries.exceptions import DuplicatePackageError
from locker.deliveries.models import DeliveryModel
from locker.deliveries.schemas import Delivery, ReservationIn
from locker.lockers.models import LockerModel
from locker.lockers.schemas import Locker

# Código SQLSTATE de PostgreSQL para una fila que incumple una restricción de unicidad
UNIQUE_VIOLATION = "23505"

# Columnas de la entrega tal como la ve la API (§8.4): las de deliveries más el edificio, la etiqueta y la talla
# de su taquilla, que salen de unir con lockers. Las comparten la consulta y los UPDATE ... RETURNING
DELIVERY_COLUMNS = (
    DeliveryModel.id,
    DeliveryModel.status,
    LockerModel.building_id,
    LockerModel.label.label("locker_label"),
    LockerModel.size,
    DeliveryModel.carrier,
    DeliveryModel.tracking_ref,
    DeliveryModel.recipient,
    DeliveryModel.deposited_at,
    DeliveryModel.picked_up_at,
)


class PickedUpDelivery(NamedTuple):
    """Una entrega recién recogida y la taquilla que ocupaba, que el servicio libera a continuación."""

    delivery: Delivery
    locker_id: uuid.UUID


class DeliveryNotice(NamedTuple):
    """Lo mínimo para avisar al residente de una entrega: a quién, en qué taquilla y en qué edificio."""

    recipient: str
    locker_label: str
    building_name: str


class DeliveryRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Crea una entrega PENDING en la taquilla asignada y la devuelve completa.
    # Si el paquete ya tiene una entrega activa, lanza DuplicatePackageError
    async def add(self, locker: Locker, carrier: str, data: ReservationIn) -> Delivery: ...

    # Lee la entrega con los datos de su taquilla. Con carrier, solo si es de ese transportista. None si no la encuentra
    async def get(self, delivery_id: uuid.UUID, carrier: str | None = None) -> Delivery | None: ...

    # Pasa la entrega del transportista de PENDING a DEPOSITED y la devuelve. None si no ha cambiado ninguna fila
    async def deposit(self, delivery_id: uuid.UUID, carrier: str) -> Delivery | None: ...

    # Pasa la entrega de DEPOSITED a PICKED_UP y la devuelve con su taquilla. None si no ha cambiado ninguna fila
    async def pick_up(self, delivery_id: uuid.UUID) -> PickedUpDelivery | None: ...

    # Lee el destinatario, la etiqueta de la taquilla y el nombre del edificio de la entrega. None si no existe
    async def get_notice(self, delivery_id: uuid.UUID) -> DeliveryNotice | None: ...


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
        """
        Lee la entrega unida a su taquilla. Con carrier, el filtro va en la propia consulta: la entrega de otro
        transportista no se encuentra, igual que una que no existe. Sin carrier (recoger), se busca solo por id
        """
        stmt = (
            select(*DELIVERY_COLUMNS)
            .join(LockerModel, LockerModel.id == DeliveryModel.locker_id)
            .where(DeliveryModel.id == delivery_id)
        )
        if carrier is not None:
            stmt = stmt.where(DeliveryModel.carrier == carrier)

        # Convierte la fila a un schema de Pydantic, o None si no hay ninguna
        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else Delivery.model_validate(row, from_attributes=True)

    async def deposit(self, delivery_id: uuid.UUID, carrier: str) -> Delivery | None:
        """
        Cambia el estado con un UPDATE condicional, sin leerlo antes en Python (I4):

        UPDATE deliveries SET status = 'DEPOSITED', deposited_at = now()
        FROM lockers
        WHERE deliveries.id = :id AND deliveries.carrier = :carrier AND deliveries.status = 'PENDING'
          AND lockers.id = deliveries.locker_id
        RETURNING ...

        Si otra transacción está cambiando la misma entrega, el UPDATE espera a que termine y vuelve a comprobar la
        condición con la fila ya confirmada: de dos depósitos a la vez, solo uno cambia la fila
        """

        # Solo la entrega de este transportista y solo si está PENDING. La condición sobre lockers no filtra nada
        # (toda entrega tiene su taquilla): une las dos tablas para que el RETURNING devuelva la entrega completa.
        # deposited_at = now(): la hora la pone la base de datos.
        # synchronize_session=False: no hace falta actualizar objetos en memoria, la fila se lee del RETURNING
        stmt = (
            update(DeliveryModel)
            .where(
                DeliveryModel.id == delivery_id,
                DeliveryModel.carrier == carrier,
                DeliveryModel.status == "PENDING",
                LockerModel.id == DeliveryModel.locker_id,
            )
            .values(status="DEPOSITED", deposited_at=func.now())
            .returning(*DELIVERY_COLUMNS)
            .execution_options(synchronize_session=False)
        )

        # Una fila si ha cambiado la entrega; ninguna si no existe, es de otro o no estaba PENDING
        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else Delivery.model_validate(row, from_attributes=True)

    async def pick_up(self, delivery_id: uuid.UUID) -> PickedUpDelivery | None:
        """
        Cambia el estado con un UPDATE condicional, sin leerlo antes en Python (I4):

        UPDATE deliveries SET status = 'PICKED_UP', picked_up_at = now()
        FROM lockers
        WHERE deliveries.id = :id AND deliveries.status = 'DEPOSITED' AND lockers.id = deliveries.locker_id
        RETURNING ..., deliveries.locker_id

        Si otra recogida de la misma entrega está en curso, el UPDATE espera a que termine y vuelve a comprobar la
        condición con la fila ya confirmada: de dos recogidas a la vez, solo una cambia la fila
        """

        # Solo si está DEPOSITED. Sin transportista: recoge el residente, que se identifica con el código.
        # Como en deposit, la condición sobre lockers solo une las tablas para el RETURNING.
        # Además de la entrega, devuelve su taquilla: es la que hay que liberar
        stmt = (
            update(DeliveryModel)
            .where(
                DeliveryModel.id == delivery_id,
                DeliveryModel.status == "DEPOSITED",
                LockerModel.id == DeliveryModel.locker_id,
            )
            .values(status="PICKED_UP", picked_up_at=func.now())
            .returning(*DELIVERY_COLUMNS, DeliveryModel.locker_id)
            .execution_options(synchronize_session=False)
        )

        # Una fila si ha cambiado la entrega; ninguna si ya no estaba DEPOSITED (otra recogida ganó)
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return PickedUpDelivery(Delivery.model_validate(row, from_attributes=True), row.locker_id)

    async def get_notice(self, delivery_id: uuid.UUID) -> DeliveryNotice | None:
        """
        Lee lo que necesita el aviso al residente, uniendo la entrega con su taquilla y su edificio: el destinatario,
        la etiqueta de la taquilla y el nombre del edificio. Nada más: el aviso no necesita el resto de la entrega
        """
        stmt = (
            select(DeliveryModel.recipient, LockerModel.label, BuildingModel.name)
            .join(LockerModel, LockerModel.id == DeliveryModel.locker_id)
            .join(BuildingModel, BuildingModel.id == LockerModel.building_id)
            .where(DeliveryModel.id == delivery_id)
        )

        # Convierte la fila al resultado, o None si la entrega no existe
        row = (await self._session.execute(stmt)).one_or_none()
        return (
            None if row is None else DeliveryNotice(recipient=row.recipient, locker_label=row.label, building_name=row.name)
        )
