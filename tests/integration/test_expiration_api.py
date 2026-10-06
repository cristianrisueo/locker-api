# Una entrega caducada vista desde la API: se consulta como EXPIRED y no se puede depositar ni recoger.
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.pickup_code import derive
from tests.integration.conftest import SECRETO_RECOGIDA, Caducar, CrearEdificio, Reservar, vencer

# El 409 de una operación que el estado de la entrega no permite (§8.3)
ESTADO_INVALIDO = {"code": "INVALID_STATE", "detail": "La entrega no está en un estado que permita esta operación"}


@pytest.fixture
async def caducada(
    session: AsyncSession,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
) -> dict[str, Any]:
    """Una reserva que ha caducado de verdad (vencida y pasada por expire_next). Devuelve la respuesta de la reserva."""
    edificio = await crear_edificio({"M": 1})
    respuesta = await reservar(cabeceras_transportista, edificio, idempotency_key="clave-de-la-caducada")
    assert respuesta.status_code == 201
    reserva: dict[str, Any] = respuesta.json()
    await vencer(session, reserva["id"])
    assert await caducar() is True
    return reserva


async def estado_en_bd(session: AsyncSession) -> tuple[str, str, int]:
    """(estado de la entrega, estado de su taquilla, eventos del outbox): lo que de verdad hay en la base de datos."""
    fila = (
        await session.execute(
            text(
                "SELECT d.status, l.status AS locker_status, (SELECT count(*) FROM outbox_events) AS eventos "
                "FROM deliveries d JOIN lockers l ON l.id = d.locker_id"
            )
        )
    ).one()
    await session.rollback()
    return fila.status, fila.locker_status, fila.eventos


async def test_consultar_una_entrega_caducada_devuelve_expired(
    client: AsyncClient, caducada: dict[str, Any], cabeceras_transportista: dict[str, str]
) -> None:
    """«[F6-06]» El transportista descubre la caducidad al consultar: 200 con la entrega en EXPIRED (A6)."""
    respuesta = await client.get(f"/v1/deliveries/{caducada['id']}", headers=cabeceras_transportista)

    assert respuesta.status_code == 200
    assert respuesta.json() == {**caducada, "status": "EXPIRED"}


async def test_depositar_una_entrega_caducada_devuelve_409(
    session: AsyncSession, client: AsyncClient, caducada: dict[str, Any], cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F6-06]» Depositar una entrega caducada da 409 INVALID_STATE, como una ya recogida: el UPDATE condicional no
    cambia nada (no está PENDING) y la entrega leída después no está DEPOSITED. No se apunta ningún evento y la
    taquilla sigue libre. Si el servicio solo diera 409 con PICKED_UP, la devolvería con 200 como si se hubiera depositado
    """
    respuesta = await client.post(f"/v1/deliveries/{caducada['id']}/deposit", headers=cabeceras_transportista)

    assert respuesta.status_code == 409
    assert respuesta.json() == ESTADO_INVALIDO
    assert await estado_en_bd(session) == ("EXPIRED", "FREE", 0)


async def test_recoger_una_entrega_caducada_devuelve_409(
    session: AsyncSession, client: AsyncClient, caducada: dict[str, Any]
) -> None:
    """
    «[F6-06]» Recoger una entrega caducada, incluso con el código correcto, da 409 INVALID_STATE: no está DEPOSITED.
    La entrega y la taquilla no cambian
    """
    codigo = derive(SECRETO_RECOGIDA, uuid.UUID(caducada["id"]))

    respuesta = await client.post(f"/v1/deliveries/{caducada['id']}/pickup", json={"code": codigo})

    assert respuesta.status_code == 409
    assert respuesta.json() == ESTADO_INVALIDO
    assert await estado_en_bd(session) == ("EXPIRED", "FREE", 0)


async def test_repetir_la_reserva_caducada_devuelve_la_respuesta_original(
    caducada: dict[str, Any], reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F6-06]» Repetir la reserva con la misma Idempotency-Key devuelve la respuesta original, en PENDING, aunque la
    entrega ya haya caducado (§8.4, como F3-09): la clave guarda la respuesta, no consulta el estado actual
    """
    respuesta = await reservar(cabeceras_transportista, caducada["building_id"], idempotency_key="clave-de-la-caducada")

    assert respuesta.status_code == 201
    assert respuesta.json() == caducada
