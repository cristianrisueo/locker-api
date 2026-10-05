# Integridad de la tabla lockers, llamando al repositorio directamente.
# Son casos inalcanzables por HTTP: Pydantic rechaza la talla antes, y ningún endpoint escribe un estado inventado.
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.repository import SqlBuildingRepository
from locker.buildings.schemas import BuildingIn
from locker.lockers.repository import SqlLockerRepository
from locker.lockers.schemas import Size

# Código SQLSTATE de PostgreSQL para una fila que incumple un CHECK
CHECK_VIOLATION = "23514"


def restriccion_violada(error: IntegrityError) -> tuple[str | None, str | None]:
    """
    (SQLSTATE, nombre de la restricción) de un IntegrityError. exc.orig es el error del driver adaptado por
    SQLAlchemy (lleva el sqlstate) y su causa es la excepción de asyncpg (lleva constraint_name)
    """
    original = error.orig
    return getattr(original, "sqlstate", None), getattr(original and original.__cause__, "constraint_name", None)


async def test_check_de_size_rechaza_una_talla_invalida(session: AsyncSession) -> None:
    """
    «[F1-11]» ck_lockers_size rechaza una talla que no es S, M ni L. alembic check no compara los CHECK:
    este test es la prueba de que la migración los creó, y con el nombre correcto.
    """
    edificio = await SqlBuildingRepository(session).add(BuildingIn(name="Edificio Sol"))

    # cast engaña a mypy: el repositorio espera S, M o L, y aquí se le pasa otra cosa a propósito
    with pytest.raises(IntegrityError) as error:
        await SqlLockerRepository(session).add_many(edificio.id, cast(Size, "X"), ["X-01"])

    assert restriccion_violada(error.value) == (CHECK_VIOLATION, "ck_lockers_size")


async def test_check_de_status_rechaza_un_estado_invalido(session: AsyncSession) -> None:
    """«[F1-11]» ck_lockers_status rechaza un estado que no es FREE ni BUSY, aunque se escriba directamente en SQL."""
    edificio = await SqlBuildingRepository(session).add(BuildingIn(name="Edificio Sol"))
    await SqlLockerRepository(session).add_many(edificio.id, "M", ["M-01"])

    with pytest.raises(IntegrityError) as error:
        await session.execute(text("UPDATE lockers SET status = 'GONE'"))

    assert restriccion_violada(error.value) == (CHECK_VIOLATION, "ck_lockers_status")
