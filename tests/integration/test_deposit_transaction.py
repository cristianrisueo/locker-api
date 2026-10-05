# Atomicidad del depósito: el cambio de estado y el evento se confirman o se deshacen juntos (I6). Sin dobles de prueba.
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.deliveries.repository import SqlDeliveryRepository
from locker.outbox.events import DELIVERY_DEPOSITED, delivery_deposited
from locker.outbox.repository import SqlOutboxRepository
from tests.integration.conftest import CrearEdificio, Reservar


class FalloProvocado(Exception):
    """Un error cualquiera después de depositar, lanzado por el propio test."""


async def entrega_en_bd(session: AsyncSession, entrega: str) -> tuple[str, datetime | None]:
    """(estado, deposited_at) de la entrega: lo que de verdad hay en la base de datos."""
    fila = (await session.execute(text("SELECT status, deposited_at FROM deliveries WHERE id = :id"), {"id": entrega})).one()
    return fila.status, fila.deposited_at


async def eventos(session: AsyncSession) -> list[dict[str, Any]]:
    """Todas las filas de outbox_events, con todas sus columnas, por id."""
    filas = await session.execute(text("SELECT * FROM outbox_events ORDER BY id"))
    return [dict(fila._mapping) for fila in filas]


@pytest.fixture
async def outbox_que_falla(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """
    Hace fallar de verdad todo INSERT en outbox_events: un trigger que lanza un error de PostgreSQL. Así el fallo
    llega por el mismo camino que uno real (el driver), sin sustituir ninguna pieza. Se elimina al terminar el test
    """
    async with session_factory() as s:
        await s.execute(
            text(
                "CREATE FUNCTION fallar_evento() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'fallo provocado al apuntar el evento'; END $$"
            )
        )
        await s.execute(
            text("CREATE TRIGGER fallar_evento BEFORE INSERT ON outbox_events FOR EACH ROW EXECUTE FUNCTION fallar_evento()")
        )
        await s.commit()

    yield

    async with session_factory() as s:
        await s.execute(text("DROP TRIGGER fallar_evento ON outbox_events"))
        await s.execute(text("DROP FUNCTION fallar_evento()"))
        await s.commit()


async def test_si_algo_falla_tras_depositar_ni_el_estado_ni_el_evento_persisten(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F4-06]» A nivel de repositorio: dentro de una transacción se deposita y se apunta el evento, y después algo
    falla. Ni la entrega queda DEPOSITED ni el evento existe. Prueba que los repositorios no confirman nada por su
    cuenta (I5): todo depende de la transacción que abre quien los usa.
    """
    edificio = await crear_edificio({"M": 1})
    reserva = (await reservar(cabeceras_transportista, edificio)).json()
    entrega = uuid.UUID(reserva["id"])

    with pytest.raises(FalloProvocado):
        async with session.begin():
            depositada = await SqlDeliveryRepository(session).deposit(entrega, "SEUR")
            assert depositada is not None
            await SqlOutboxRepository(session).add(DELIVERY_DEPOSITED, delivery_deposited(entrega))
            raise FalloProvocado

    assert await entrega_en_bd(session, reserva["id"]) == ("PENDING", None)
    assert await eventos(session) == []


async def test_si_falla_el_evento_el_deposito_se_deshace(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    outbox_que_falla: None,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-06]» A nivel de servicio, con un fallo real de PostgreSQL: el INSERT del evento falla, el error llega al
    cliente y la entrega sigue PENDING, sin evento. Si el evento se apuntara en otra transacción que la del cambio
    de estado, la entrega quedaría DEPOSITED y el residente nunca recibiría el aviso.
    """
    edificio = await crear_edificio({"M": 1})
    reserva = (await reservar(cabeceras_transportista, edificio)).json()

    # El error no se traduce a ningún código del catálogo: sale de la app tal cual (en producción, un 500)
    with pytest.raises(DBAPIError, match="fallo provocado al apuntar el evento"):
        await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)

    # Una sesión que se cierra aquí mismo, y no la fixture session: su transacción abierta retendría la tabla
    # outbox_events, y el DROP TRIGGER de outbox_que_falla (que se deshace antes que session) esperaría para siempre
    async with session_factory() as session:
        assert await entrega_en_bd(session, reserva["id"]) == ("PENDING", None)
        assert await eventos(session) == []
