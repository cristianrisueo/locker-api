# Integridad de la tabla deliveries, con inserts directos en la base de datos.
# Prueban los índices únicos parciales por sí solos, sin el servicio ni la traducción de errores del repositorio.
import uuid

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.repository import SqlBuildingRepository
from locker.buildings.schemas import BuildingIn
from locker.deliveries.models import DeliveryModel
from locker.lockers.repository import SqlLockerRepository
from tests.integration.conftest import restriccion_violada

# Código SQLSTATE de PostgreSQL para una fila que incumple una restricción de unicidad
UNIQUE_VIOLATION = "23505"


async def crear_taquillas(session: AsyncSession, cuantas: int) -> list[uuid.UUID]:
    """Crea un edificio con taquillas M y devuelve sus ids."""
    edificio = await SqlBuildingRepository(session).add(BuildingIn(name="Edificio Sol"))
    etiquetas = [f"M-{n:02d}" for n in range(1, cuantas + 1)]
    taquillas = await SqlLockerRepository(session).add_many(edificio.id, "M", etiquetas)
    return [taquilla.id for taquilla in taquillas]


async def insertar_entrega(
    session: AsyncSession, locker_id: uuid.UUID, tracking_ref: str, status: str = "PENDING", carrier: str = "SEUR"
) -> None:
    """
    Inserta una entrega directamente en la tabla, sin pasar por el repositorio. Desde F6 lleva siempre un plazo
    (expires_at), que una PENDING necesita; su valor no importa a estos tests
    """
    await session.execute(
        insert(DeliveryModel).values(
            locker_id=locker_id,
            carrier=carrier,
            tracking_ref=tracking_ref,
            recipient="vecino@example.com",
            status=status,
            expires_at=func.now(),
        )
    )


async def test_una_taquilla_no_admite_dos_entregas_activas(session: AsyncSession) -> None:
    """
    «[F2-07]» uq_deliveries_active_locker rechaza una segunda entrega activa en la misma taquilla, aunque
    sea de otro paquete. Es la red de seguridad de la asignación (I1): si dos reservas se llevaran la misma
    taquilla, la base de datos lo impediría.
    """
    (taquilla,) = await crear_taquillas(session, 1)
    await insertar_entrega(session, taquilla, "ES123")

    with pytest.raises(IntegrityError) as error:
        await insertar_entrega(session, taquilla, "ES456", status="DEPOSITED")

    assert restriccion_violada(error.value) == (UNIQUE_VIOLATION, "uq_deliveries_active_locker")


async def test_un_paquete_no_admite_dos_entregas_activas(session: AsyncSession) -> None:
    """
    «[F2-07]» uq_deliveries_active_package rechaza una segunda entrega activa del mismo paquete (mismo
    transportista y referencia), aunque vaya a otra taquilla (I2).
    """
    primera, segunda = await crear_taquillas(session, 2)
    await insertar_entrega(session, primera, "ES123", status="DEPOSITED")

    with pytest.raises(IntegrityError) as error:
        await insertar_entrega(session, segunda, "ES123")

    assert restriccion_violada(error.value) == (UNIQUE_VIOLATION, "uq_deliveries_active_package")


async def test_una_entrega_recogida_no_cuenta_como_activa(session: AsyncSession) -> None:
    """
    «[F2-08]» Los índices son parciales: una entrega PICKED_UP no ocupa ni su taquilla ni su paquete.
    Se puede crear otra entrega activa para la misma taquilla y el mismo paquete.
    """
    (taquilla,) = await crear_taquillas(session, 1)
    await insertar_entrega(session, taquilla, "ES123", status="PICKED_UP")

    await insertar_entrega(session, taquilla, "ES123")

    estados = await session.scalars(select(DeliveryModel.status).order_by(DeliveryModel.id))
    assert estados.all() == ["PICKED_UP", "PENDING"]
