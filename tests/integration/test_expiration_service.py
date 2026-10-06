# Caducidad de reservas (expire_next): qué caduca, qué no, y que la taquilla y el paquete quedan libres.
import logging
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.pickup_code import derive
from tests.integration.conftest import SECRETO_RECOGIDA, Caducar, CrearEdificio, Reservar, vencer


async def estados(session: AsyncSession) -> dict[str, tuple[str, str]]:
    """(estado de la entrega, estado de su taquilla) de cada entrega, por id: lo que de verdad hay en la BD."""
    filas = await session.execute(
        text("SELECT d.id, d.status, l.status AS locker_status FROM deliveries d JOIN lockers l ON l.id = d.locker_id")
    )
    resultado = {str(fila.id): (fila.status, fila.locker_status) for fila in filas}
    await session.rollback()
    return resultado


async def tablas(session: AsyncSession) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Todas las filas de deliveries y de lockers, con todas sus columnas, por id."""
    entregas = await session.execute(text("SELECT * FROM deliveries ORDER BY id"))
    taquillas = await session.execute(text("SELECT * FROM lockers ORDER BY id"))
    resultado = [dict(f._mapping) for f in entregas], [dict(f._mapping) for f in taquillas]
    await session.rollback()
    return resultado


async def test_caducar_pasa_la_reserva_vencida_a_expired_y_libera_su_taquilla(
    session: AsyncSession,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    «[F6-03]» De dos reservas, solo la vencida caduca: pasa a EXPIRED y su taquilla a FREE, y expire_next devuelve
    True. La otra sigue PENDING con su taquilla BUSY. La caducidad deja una línea INFO con el id de la entrega
    """
    edificio = await crear_edificio({"M": 2})
    vencida = (await reservar(cabeceras_transportista, edificio, tracking_ref="ES1")).json()["id"]
    vigente = (await reservar(cabeceras_transportista, edificio, tracking_ref="ES2")).json()["id"]
    await vencer(session, vencida)

    with caplog.at_level(logging.INFO, logger="locker.deliveries.expiration"):
        assert await caducar() is True

    assert await estados(session) == {vencida: ("EXPIRED", "FREE"), vigente: ("PENDING", "BUSY")}
    registros = [r for r in caplog.records if r.name == "locker.deliveries.expiration"]
    assert [(r.levelname, r.getMessage(), getattr(r, "delivery_id", None)) for r in registros] == [
        ("INFO", "Reserva caducada: su taquilla queda libre", vencida)
    ]


async def test_caducar_y_liberar_la_taquilla_van_en_la_misma_transaccion(
    session: AsyncSession,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
) -> None:
    """
    «[F6-03]» Si la taquilla de la reserva vencida no está BUSY (un estado imposible, forzado por SQL), liberarla
    falla y el error deshace también la caducidad: la entrega sigue PENDING (I14). Si la caducidad se confirmara por
    su cuenta, la entrega quedaría EXPIRED aunque liberar la taquilla hubiera fallado
    """
    edificio = await crear_edificio({"M": 1})
    entrega = (await reservar(cabeceras_transportista, edificio)).json()["id"]
    await vencer(session, entrega)
    await session.execute(text("UPDATE lockers SET status = 'FREE'"))
    await session.commit()

    with pytest.raises(RuntimeError, match="de una reserva caducada no estaba ocupada"):
        await caducar()

    assert await estados(session) == {entrega: ("PENDING", "FREE")}


async def test_caducar_no_toca_lo_que_no_ha_vencido_ni_lo_depositado_o_recogido(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caducar: Caducar,
) -> None:
    """
    «[F6-04]» Sin ninguna reserva PENDING vencida, expire_next devuelve False y no cambia nada: ni una PENDING con
    el plazo por delante, ni una DEPOSITED o una PICKED_UP cuyo expires_at ya pasó (el plazo solo cuenta mientras
    la entrega está PENDING)
    """
    edificio = await crear_edificio({"M": 3})
    await reservar(cabeceras_transportista, edificio, tracking_ref="ES1")
    depositada = (await reservar(cabeceras_transportista, edificio, tracking_ref="ES2")).json()["id"]
    recogida = (await reservar(cabeceras_transportista, edificio, tracking_ref="ES3")).json()["id"]
    for entrega in (depositada, recogida):
        respuesta = await client.post(f"/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista)
        assert respuesta.status_code == 200
        await vencer(session, entrega)
    codigo = derive(SECRETO_RECOGIDA, uuid.UUID(recogida))
    respuesta = await client.post(f"/v1/deliveries/{recogida}/pickup", json={"code": codigo})
    assert respuesta.status_code == 200
    antes = await tablas(session)

    assert await caducar() is False

    assert await tablas(session) == antes


async def test_tras_caducar_el_paquete_y_la_taquilla_se_pueden_reservar_otra_vez(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    cabeceras_operador: dict[str, str],
    caducar: Caducar,
) -> None:
    """
    «[F6-05]» Una reserva caducada ya no es activa: la capacidad cuenta su taquilla como libre, y el mismo paquete
    se puede reservar otra vez en la misma taquilla (los índices únicos parciales solo cuentan PENDING y DEPOSITED)
    """
    edificio = await crear_edificio({"M": 1})
    caducada = (await reservar(cabeceras_transportista, edificio, tracking_ref="ES123")).json()["id"]
    await vencer(session, caducada)
    assert await caducar() is True

    capacidad = await client.get(f"/v1/buildings/{edificio}/capacity", headers=cabeceras_operador)
    assert capacidad.json() == {"building_id": edificio, "sizes": [{"size": "M", "total": 1, "free": 1}]}

    respuesta = await reservar(cabeceras_transportista, edificio, tracking_ref="ES123")
    assert respuesta.status_code == 201
    nueva = respuesta.json()
    assert (nueva["tracking_ref"], nueva["locker_label"], nueva["status"]) == ("ES123", "M-01", "PENDING")
    assert await estados(session) == {caducada: ("EXPIRED", "BUSY"), nueva["id"]: ("PENDING", "BUSY")}
