# Reservar por la API: asignación de taquilla, errores y paquetes duplicados.
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CrearEdificio, Reservar


async def taquillas(session: AsyncSession, edificio: str) -> list[tuple[str, str]]:
    """(etiqueta, estado) de las taquillas del edificio, por etiqueta: lo que de verdad hay en la base de datos."""
    filas = await session.execute(
        text("SELECT label, status FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio}
    )
    return [(fila.label, fila.status) for fila in filas]


async def entregas(session: AsyncSession) -> list[tuple[str, str, str, str]]:
    """(id, transportista, referencia, estado) de todas las entregas de la base de datos, por id."""
    filas = await session.execute(text("SELECT id, carrier, tracking_ref, status FROM deliveries ORDER BY id"))
    return [(str(fila.id), fila.carrier, fila.tracking_ref, fila.status) for fila in filas]


async def test_reservar_asigna_una_taquilla_libre_de_la_talla_pedida(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F2-01]» Reservar ocupa la primera taquilla libre de la talla pedida (la de id más antiguo) y crea la
    entrega en PENDING. El transportista sale de la clave (SEUR), no del cuerpo. Las demás taquillas no cambian.
    """
    edificio = await crear_edificio({"S": 1, "M": 2})

    respuesta = await reservar(cabeceras_transportista, edificio, size="M", tracking_ref="ES123")

    assert respuesta.status_code == 201
    entrega = respuesta.json()
    assert entrega == {
        "id": entrega["id"],
        "status": "PENDING",
        "building_id": edificio,
        "locker_label": "M-01",
        "size": "M",
        "carrier": "SEUR",
        "tracking_ref": "ES123",
        "recipient": "vecino@example.com",
        "deposited_at": None,
        "picked_up_at": None,
    }
    assert uuid.UUID(entrega["id"]).version == 7
    assert await taquillas(session, edificio) == [("M-01", "BUSY"), ("M-02", "FREE"), ("S-01", "FREE")]
    assert await entregas(session) == [(entrega["id"], "SEUR", "ES123", "PENDING")]


async def test_sin_taquilla_libre_de_la_talla_devuelve_409_y_no_asigna_una_mayor(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F2-02]» Con la única M ocupada, otra reserva M recibe 409 NO_LOCKER_AVAILABLE aunque quede una L libre:
    solo se asigna la talla exacta (D3). El 409 no deja rastro: ni entrega nueva ni taquilla ocupada de más.
    """
    edificio = await crear_edificio({"S": 1, "M": 1, "L": 1})
    primera = await reservar(cabeceras_transportista, edificio, size="M", tracking_ref="ES123")
    assert primera.status_code == 201

    respuesta = await reservar(cabeceras_transportista, edificio, size="M", tracking_ref="ES456")

    assert respuesta.status_code == 409
    assert respuesta.json() == {"code": "NO_LOCKER_AVAILABLE", "detail": "No quedan taquillas de esta talla disponibles"}
    assert await taquillas(session, edificio) == [("L-01", "FREE"), ("M-01", "BUSY"), ("S-01", "FREE")]
    assert await entregas(session) == [(primera.json()["id"], "SEUR", "ES123", "PENDING")]


async def test_reservar_en_un_edificio_inexistente_devuelve_404(
    session: AsyncSession, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F2-03]» Un edificio que no existe es un 404 con su id en el detail, no un 409 por falta de taquilla."""
    edificio = str(uuid.uuid7())

    respuesta = await reservar(cabeceras_transportista, edificio)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Edificio {edificio} no encontrado"}
    assert await entregas(session) == []


async def test_reservar_un_paquete_con_reserva_activa_devuelve_409(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F2-04]» El mismo paquete (mismo transportista y referencia) con una entrega activa es un 409 DUPLICATE_PACKAGE.
    La segunda reserva llegó a ocupar M-02 antes de chocar con el índice: el rollback la deja libre otra vez.
    """
    edificio = await crear_edificio({"M": 2})
    primera = await reservar(cabeceras_transportista, edificio, tracking_ref="ES123")
    assert primera.status_code == 201

    respuesta = await reservar(cabeceras_transportista, edificio, tracking_ref="ES123")

    assert respuesta.status_code == 409
    assert respuesta.json() == {"code": "DUPLICATE_PACKAGE", "detail": "Este paquete ya tiene una reserva activa"}
    assert await taquillas(session, edificio) == [("M-01", "BUSY"), ("M-02", "FREE")]
    assert await entregas(session) == [(primera.json()["id"], "SEUR", "ES123", "PENDING")]


async def test_la_misma_referencia_de_otro_transportista_es_otra_reserva(
    session: AsyncSession,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    cabeceras_correos: dict[str, str],
) -> None:
    """
    «[F2-05]» Un paquete es transportista + referencia: ES123 de SEUR y ES123 de Correos Express son paquetes
    distintos, y cada uno se queda con su taquilla.
    """
    edificio = await crear_edificio({"M": 2})
    seur = await reservar(cabeceras_transportista, edificio, tracking_ref="ES123")

    correos = await reservar(cabeceras_correos, edificio, tracking_ref="ES123")

    assert (seur.status_code, correos.status_code) == (201, 201)
    assert (seur.json()["locker_label"], correos.json()["locker_label"]) == ("M-01", "M-02")
    assert correos.json()["carrier"] == "Correos Express"
    assert await entregas(session) == [
        (seur.json()["id"], "SEUR", "ES123", "PENDING"),
        (correos.json()["id"], "Correos Express", "ES123", "PENDING"),
    ]


@pytest.mark.parametrize(
    ("cabeceras", "esperado"),
    [
        ({}, (401, {"code": "UNAUTHENTICATED", "detail": "Falta la clave de API o no es válida"})),
        ("cabeceras_operador", (403, {"code": "FORBIDDEN", "detail": "Esta clave no tiene permiso para esta operación"})),
    ],
    ids=["sin-clave", "operador"],
)
async def test_solo_un_transportista_puede_reservar(
    request: pytest.FixtureRequest,
    session: AsyncSession,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras: dict[str, str] | str,
    esperado: tuple[int, dict[str, str]],
) -> None:
    """«[F2-03]» Sin clave es un 401 y con la del operador un 403. Ninguno ocupa la taquilla."""
    edificio = await crear_edificio({"M": 1})
    # Las cabeceras del operador son una fixture: el parámetro trae su nombre y se piden aquí
    valor: dict[str, str] = request.getfixturevalue(cabeceras) if isinstance(cabeceras, str) else cabeceras

    respuesta = await reservar(valor, edificio)

    assert (respuesta.status_code, respuesta.json()) == esperado
    assert await taquillas(session, edificio) == [("M-01", "FREE")]


@pytest.mark.parametrize(
    ("cambio", "detail"),
    [
        ({"size": "XL"}, "size: Input should be 'S', 'M' or 'L'"),
        ({"tracking_ref": "   "}, "tracking_ref: String should have at least 1 character"),
        ({"carrier": "MRW"}, "carrier: Extra inputs are not permitted"),
    ],
    ids=["talla-invalida", "referencia-vacia", "campo-extra"],
)
async def test_cuerpo_invalido_devuelve_422(
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    cabeceras_transportista: dict[str, str],
    cambio: dict[str, Any],
    detail: str,
) -> None:
    """
    «[F2-03]» Una talla que no existe, una referencia que se queda vacía al quitarle los espacios y un campo
    que no es del cuerpo (el transportista sale de la clave, no se puede elegir) son un 422 VALIDATION_ERROR.
    """
    edificio = await crear_edificio({"M": 1})
    cuerpo = {"building_id": edificio, "size": "M", "tracking_ref": "ES123", "recipient": "vecino@example.com", **cambio}

    respuesta = await client.post("/v1/deliveries", json=cuerpo, headers=cabeceras_transportista)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": detail}
