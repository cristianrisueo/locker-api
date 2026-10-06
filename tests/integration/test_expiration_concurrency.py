# Caducidad bajo concurrencia: la carrera con depositar y dos workers caducando a la vez.
import asyncio
import logging
import uuid
from collections.abc import Coroutine
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.deliveries.repository import SqlDeliveryRepository
from locker.lockers.repository import SqlLockerRepository
from tests.integration.conftest import (
    AbrirConexiones,
    Caducar,
    CrearEdificio,
    Reservar,
    bloqueos_en_espera,
    vencer,
)

# El 409 de una operación que el estado de la entrega no permite (§8.3)
ESTADO_INVALIDO = {"code": "INVALID_STATE", "detail": "La entrega no está en un estado que permita esta operación"}


async def estado_en_bd(session: AsyncSession, entrega: str) -> tuple[str, str, int]:
    """(estado de la entrega, estado de su taquilla, eventos de esa entrega en el outbox)."""
    fila = (
        await session.execute(
            text(
                "SELECT d.status, l.status AS locker_status, "
                "(SELECT count(*) FROM outbox_events WHERE payload->>'delivery_id' = :id) AS eventos "
                "FROM deliveries d JOIN lockers l ON l.id = d.locker_id WHERE d.id = CAST(:id AS uuid)"
            ),
            {"id": entrega},
        )
    ).one()
    await session.rollback()
    return fila.status, fila.locker_status, fila.eventos


async def reservar_vencida(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras: dict[str, str]
) -> str:
    """Un edificio con una taquilla M y una reserva en ella con el plazo ya vencido. Devuelve el id de la entrega."""
    edificio = await crear_edificio({"M": 1})
    respuesta = await reservar(cabeceras, edificio, tracking_ref=f"ES{uuid.uuid4().hex[:8]}")
    assert respuesta.status_code == 201
    entrega: str = respuesta.json()["id"]
    await vencer(session, entrega)
    return entrega


async def sin_esperar(pasada: Coroutine[Any, Any, bool], observador: AsyncSession) -> bool:
    """
    Lanza una pasada de la caducidad como tarea y comprueba, mientras dura, que no se queda parada en un bloqueo.
    Devuelve lo que devuelve la pasada. Si la ve esperando, la cancela y el test falla en ese momento
    """
    tarea = asyncio.create_task(pasada)
    try:
        while not tarea.done():
            assert await bloqueos_en_espera(observador) == 0, "expire_next se quedó esperando a la entrega bloqueada"
        return tarea.result()
    finally:
        tarea.cancel()


async def test_depositar_y_caducar_a_la_vez_gana_uno_solo(
    session: AsyncSession,
    client: AsyncClient,
    abrir_conexiones: AbrirConexiones,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
) -> None:
    """
    «[F6-07]» Con el plazo vencido, el depósito por la API y una pasada de la caducidad compiten por la misma
    reserva, varias veces. Gana exactamente uno y el estado final es coherente: o depositada (200, la caducidad no
    encuentra nada, taquilla BUSY y un evento), o caducada (409, taquilla FREE y ningún evento). Nunca otra
    combinación. Quién gana depende del azar: los casos deterministas de abajo fuerzan cada orden
    """
    for _ in range(5):
        entrega = await reservar_vencida(session, crear_edificio, reservar, cabeceras_transportista)

        # Las dos operaciones se lanzan a la vez en el mismo bucle de eventos, con sus conexiones ya abiertas
        await abrir_conexiones(2)
        deposito, caducada = await asyncio.gather(
            client.post(f"/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista), caducar()
        )

        if caducada:
            assert (deposito.status_code, deposito.json()) == (409, ESTADO_INVALIDO)
            assert await estado_en_bd(session, entrega) == ("EXPIRED", "FREE", 0)
        else:
            assert deposito.status_code == 200
            assert await estado_en_bd(session, entrega) == ("DEPOSITED", "BUSY", 1)


async def test_caducar_salta_sin_esperar_una_reserva_que_se_esta_depositando(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
) -> None:
    """
    «[F6-07]» Versión determinista, gana depositar. Un depósito en curso ya ha pasado la reserva vencida a
    DEPOSITED, sin confirmar. La caducidad no lo espera: salta la fila bloqueada y devuelve False. Al confirmar el
    depósito, la entrega queda DEPOSITED con su taquilla BUSY, y la caducidad sigue sin encontrar nada. Sin SKIP
    LOCKED (o sin ningún bloqueo), la caducidad se quedaría esperando al depósito
    """
    entrega = await reservar_vencida(session, crear_edificio, reservar, cabeceras_transportista)

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otra, session_factory() as observador:
        # Otro depósito en curso: cambia el estado y deja la transacción abierta
        await otra.begin()
        assert await SqlDeliveryRepository(otra).deposit(uuid.UUID(entrega), "SEUR") is not None

        assert await sin_esperar(caducar(), observador) is False

        # El depósito confirma
        await otra.commit()

    assert await caducar() is False
    assert await estado_en_bd(session, entrega) == ("DEPOSITED", "BUSY", 0)


async def test_depositar_una_reserva_que_se_esta_caducando_devuelve_409(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F6-07]» Versión determinista, gana caducar. Una caducidad en curso ya ha pasado la reserva a EXPIRED y ha
    liberado su taquilla, sin confirmar. El depósito por la API se queda esperando en su UPDATE condicional. Al
    confirmar la caducidad, PostgreSQL vuelve a evaluar la condición con la fila confirmada, el depósito no cambia
    nada y responde 409 INVALID_STATE, sin evento. Sin «status = 'PENDING'» en el UPDATE de depositar, la entrega
    quedaría DEPOSITED con su taquilla FREE (lo que prohíbe I14)
    """
    entrega = await reservar_vencida(session, crear_edificio, reservar, cabeceras_transportista)

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otra, session_factory() as observador:
        # Otra caducidad en curso: caduca la reserva, libera la taquilla y deja la transacción abierta
        await otra.begin()
        caducada = await SqlDeliveryRepository(otra).expire_due()
        assert caducada is not None
        assert await SqlLockerRepository(otra).release(caducada.locker_id)

        # El depósito por la API se lanza como tarea y se espera, sin sleep, hasta verlo parado en un bloqueo
        tarea = asyncio.create_task(client.post(f"/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista))
        while await bloqueos_en_espera(observador) == 0:
            assert not tarea.done(), "el depósito terminó sin esperar a la caducidad en curso"

        # La caducidad confirma: eso libera la fila de la entrega
        await otra.commit()

        respuesta = await tarea

    assert (respuesta.status_code, respuesta.json()) == (409, ESTADO_INVALIDO)
    assert await estado_en_bd(session, entrega) == ("EXPIRED", "FREE", 0)


async def test_dos_workers_a_la_vez_caducan_cada_reserva_una_sola_vez(
    session: AsyncSession,
    abrir_conexiones: AbrirConexiones,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    «[F6-08]» Dos workers caducan a la vez 8 reservas vencidas, cada uno con su sesión en cada pasada: entre los dos
    caducan exactamente 8 (cada reserva una sola vez, según el log), y todas quedan EXPIRED con su taquilla FREE.
    Si los dos caducaran la misma, la segunda liberación fallaría o habría más de 8 caducidades
    """
    edificio = await crear_edificio({"M": 8})
    entregas = []
    for n in range(8):
        respuesta = await reservar(cabeceras_transportista, edificio, tracking_ref=f"ES{n}")
        assert respuesta.status_code == 201
        entregas.append(respuesta.json()["id"])
        await vencer(session, entregas[-1])

    async def worker() -> int:
        """Un worker que caduca reservas hasta que no encuentra ninguna libre. Devuelve cuántas ha caducado."""
        caducadas = 0
        while await caducar():
            caducadas += 1
        return caducadas

    # Los dos workers arrancan a la vez en el mismo bucle de eventos, con sus conexiones ya abiertas
    await abrir_conexiones(2)
    with caplog.at_level(logging.INFO, logger="locker.deliveries.expiration"):
        cuentas = await asyncio.gather(worker(), worker())

    assert sum(cuentas) == 8
    registros = [r for r in caplog.records if r.name == "locker.deliveries.expiration"]
    assert sorted(str(getattr(r, "delivery_id", "")) for r in registros) == sorted(entregas)
    assert [await estado_en_bd(session, entrega) for entrega in entregas] == [("EXPIRED", "FREE", 0)] * 8
