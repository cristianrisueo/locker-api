# Recoger por la API: el residente, sin clave de API, con el código derivado de la entrega.
import uuid
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.pickup_code import derive
from tests.integration.conftest import SECRETO_RECOGIDA, CrearEdificio, Reservar


def codigo_de(entrega: str) -> str:
    """El código de recogida de la entrega, calculado como lo hace el servidor: con el secreto de los tests."""
    return derive(SECRETO_RECOGIDA, uuid.UUID(entrega))


def otro_codigo(codigo: str) -> str:
    """Un código bien formado (seis cifras) pero distinto del dado."""
    return f"{(int(codigo) + 1) % 1_000_000:06d}"


async def recoger(client: AsyncClient, entrega: str, codigo: Any) -> Response:
    """Recoge la entrega como el residente: sin X-API-Key, solo con el código en el cuerpo."""
    return await client.post(f"/v1/deliveries/{entrega}/pickup", json={"code": codigo})


async def estado_en_bd(session: AsyncSession, entrega: str) -> tuple[str, datetime | None, str]:
    """(estado de la entrega, picked_up_at, estado de su taquilla): lo que de verdad hay en la base de datos."""
    fila = (
        await session.execute(
            text(
                "SELECT d.status, d.picked_up_at, l.status AS locker_status "
                "FROM deliveries d JOIN lockers l ON l.id = d.locker_id WHERE d.id = :id"
            ),
            {"id": entrega},
        )
    ).one()
    return fila.status, fila.picked_up_at, fila.locker_status


async def reservar_una(crear_edificio: CrearEdificio, reservar: Reservar, cabeceras: dict[str, str]) -> dict[str, Any]:
    """Un edificio con una taquilla M y una reserva en ella (PENDING): devuelve la entrega de la respuesta."""
    edificio = await crear_edificio({"M": 1})
    respuesta = await reservar(cabeceras, edificio)
    assert respuesta.status_code == 201
    reserva: dict[str, Any] = respuesta.json()
    return reserva


async def depositar_una(
    client: AsyncClient, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras: dict[str, str]
) -> dict[str, Any]:
    """Una entrega reservada y depositada, lista para recoger: devuelve la entrega de la respuesta del depósito."""
    reserva = await reservar_una(crear_edificio, reservar, cabeceras)
    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras)
    assert respuesta.status_code == 200
    depositada: dict[str, Any] = respuesta.json()
    return depositada


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_con_el_codigo_correcto_libera_la_taquilla(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-08]» El residente recoge con el código correcto, sin clave de API: 200 con la entrega en PICKED_UP y con
    picked_up_at, que es la hora guardada en la base de datos. La taquilla vuelve a FREE en la misma operación.
    """
    depositada = await depositar_una(client, crear_edificio, reservar, cabeceras_transportista)

    respuesta = await recoger(client, depositada["id"], codigo_de(depositada["id"]))

    assert respuesta.status_code == 200
    entrega = respuesta.json()
    assert entrega == {**depositada, "status": "PICKED_UP", "picked_up_at": entrega["picked_up_at"]}
    estado, recogida, taquilla = await estado_en_bd(session, depositada["id"])
    assert (estado, taquilla) == ("PICKED_UP", "FREE")
    assert recogida is not None
    assert datetime.fromisoformat(entrega["picked_up_at"]) == recogida


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_con_un_codigo_incorrecto_devuelve_403_y_no_cambia_nada(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-09]» Un código bien formado pero incorrecto: 403 INVALID_PICKUP_CODE con un detail fijo, que no repite
    el código recibido. La entrega sigue DEPOSITED y la taquilla ocupada.
    """
    depositada = await depositar_una(client, crear_edificio, reservar, cabeceras_transportista)

    respuesta = await recoger(client, depositada["id"], otro_codigo(codigo_de(depositada["id"])))

    assert respuesta.status_code == 403
    assert respuesta.json() == {"code": "INVALID_PICKUP_CODE", "detail": "Código de recogida incorrecto"}
    assert await estado_en_bd(session, depositada["id"]) == ("DEPOSITED", None, "BUSY")


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
@pytest.mark.parametrize(
    "codigo",
    ["12345", "1234567", "12a456", " 123456", "", 123456, None, "١٢٣٤٥٦"],
    ids=["cinco-cifras", "siete-cifras", "con-letra", "con-espacio", "vacio", "numero", "nulo", "cifras-no-ascii"],
)
async def test_recoger_con_un_codigo_mal_formado_devuelve_422(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    codigo: Any,
) -> None:
    """
    «[F4-09]» El código son exactamente seis cifras del 0 al 9, en texto. Cualquier otra cosa (otra longitud,
    letras, espacios, un número JSON, cifras de otros alfabetos) es un 422 VALIDATION_ERROR sobre el campo code,
    y la entrega no cambia.
    """
    depositada = await depositar_una(client, crear_edificio, reservar, cabeceras_transportista)

    respuesta = await recoger(client, depositada["id"], codigo)

    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "VALIDATION_ERROR"
    assert respuesta.json()["detail"].startswith("code: ")
    assert await estado_en_bd(session, depositada["id"]) == ("DEPOSITED", None, "BUSY")


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_sin_codigo_devuelve_422(client: AsyncClient) -> None:
    """«[F4-09]» Un cuerpo sin el campo code es un 422 VALIDATION_ERROR."""
    respuesta = await client.post(f"/v1/deliveries/{uuid.uuid7()}/pickup", json={})

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": "code: Field required"}


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_una_entrega_inexistente_devuelve_404(client: AsyncClient) -> None:
    """«[F4-09]» Una entrega que no existe es un 404 con su id en el detail, se envíe el código que se envíe."""
    entrega = uuid.uuid7()

    respuesta = await recoger(client, str(entrega), codigo_de(str(entrega)))

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Entrega {entrega} no encontrada"}


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_una_entrega_sin_depositar_devuelve_409(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-10]» Una entrega reservada pero sin depositar no se puede recoger, aunque el código sea correcto: 409
    INVALID_STATE. La entrega sigue PENDING y la taquilla ocupada.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)

    respuesta = await recoger(client, reserva["id"], codigo_de(reserva["id"]))

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "code": "INVALID_STATE",
        "detail": "La entrega no está en un estado que permita esta operación",
    }
    assert await estado_en_bd(session, reserva["id"]) == ("PENDING", None, "BUSY")


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_sin_depositar_con_un_codigo_incorrecto_devuelve_409(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-10]» El estado se comprueba antes que el código (§7.7): con una entrega PENDING y un código incorrecto, la
    respuesta es 409 INVALID_STATE, no 403 INVALID_PICKUP_CODE.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)

    respuesta = await recoger(client, reserva["id"], otro_codigo(codigo_de(reserva["id"])))

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "code": "INVALID_STATE",
        "detail": "La entrega no está en un estado que permita esta operación",
    }
    assert await estado_en_bd(session, reserva["id"]) == ("PENDING", None, "BUSY")


@pytest.mark.xfail(strict=True, reason="recoger todavía no existe")
async def test_recoger_dos_veces_devuelve_409(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-10]» Recoger dos veces: la segunda es un 409 INVALID_STATE (A14), y la entrega conserva el picked_up_at
    de la primera.
    """
    depositada = await depositar_una(client, crear_edificio, reservar, cabeceras_transportista)
    primera = await recoger(client, depositada["id"], codigo_de(depositada["id"]))
    assert primera.status_code == 200

    segunda = await recoger(client, depositada["id"], codigo_de(depositada["id"]))

    assert segunda.status_code == 409
    assert segunda.json() == {
        "code": "INVALID_STATE",
        "detail": "La entrega no está en un estado que permita esta operación",
    }
    estado, recogida, taquilla = await estado_en_bd(session, depositada["id"])
    assert (estado, taquilla) == ("PICKED_UP", "FREE")
    assert recogida == datetime.fromisoformat(primera.json()["picked_up_at"])
