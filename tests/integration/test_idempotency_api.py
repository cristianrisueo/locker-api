# Idempotencia de la reserva por la API: reintentos con la misma Idempotency-Key, cuerpo distinto y claves que no se guardan.
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from locker.idempotency.fingerprint import fingerprint
from tests.integration.conftest import CrearEdificio, Reservar


def cuerpo_de(edificio: str, tracking_ref: str = "ES123") -> dict[str, str]:
    """El cuerpo que envía la fixture reservar, para calcular su huella: el mismo que deja model_dump(mode="json")."""
    return {"building_id": edificio, "size": "M", "tracking_ref": tracking_ref, "recipient": "vecino@example.com"}


async def taquillas(session: AsyncSession, edificio: str) -> list[tuple[str, str]]:
    """(etiqueta, estado) de las taquillas del edificio, por etiqueta."""
    filas = await session.execute(
        text("SELECT label, status FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio}
    )
    return [(fila.label, fila.status) for fila in filas]


async def entregas(session: AsyncSession) -> list[tuple[str, str, str]]:
    """(id, transportista, referencia) de todas las entregas de la base de datos, por id."""
    filas = await session.execute(text("SELECT id, carrier, tracking_ref FROM deliveries ORDER BY id"))
    return [(str(fila.id), fila.carrier, fila.tracking_ref) for fila in filas]


async def claves(session: AsyncSession) -> list[tuple[str, str, str, Any]]:
    """(transportista, clave, huella, respuesta guardada) de todas las claves de idempotencia, por transportista y clave."""
    filas = await session.execute(
        text("SELECT carrier, key, request_hash, response_body FROM idempotency_keys ORDER BY carrier, key")
    )
    return [(fila.carrier, fila.key, fila.request_hash, fila.response_body) for fila in filas]


async def test_reintento_con_la_misma_clave_devuelve_la_misma_respuesta(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F3-02]» Repetir la reserva con la misma clave y el mismo cuerpo (un cliente que no recibió la respuesta)
    da 201 con la misma respuesta, no un 409 por paquete duplicado. Solo hay una entrega y una taquilla ocupada,
    y la clave queda guardada con la huella del cuerpo y la respuesta que se dio.
    """
    edificio = await crear_edificio({"M": 2})
    primera = await reservar(cabeceras_transportista, edificio, idempotency_key="reserva-ES123")

    repetida = await reservar(cabeceras_transportista, edificio, idempotency_key="reserva-ES123")

    assert (primera.status_code, repetida.status_code) == (201, 201)
    assert repetida.json() == primera.json()
    assert await taquillas(session, edificio) == [("M-01", "BUSY"), ("M-02", "FREE")]
    assert await entregas(session) == [(primera.json()["id"], "SEUR", "ES123")]
    assert await claves(session) == [("SEUR", "reserva-ES123", fingerprint(cuerpo_de(edificio)), primera.json())]


async def test_la_misma_clave_con_otro_cuerpo_devuelve_422(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F3-03]» La misma clave con un cuerpo distinto (otra referencia) es un error del cliente: 422
    IDEMPOTENCY_KEY_REUSED. No se reserva nada y la clave sigue guardada con la petición original.
    """
    edificio = await crear_edificio({"M": 2})
    primera = await reservar(cabeceras_transportista, edificio, tracking_ref="ES123", idempotency_key="reserva-1")

    respuesta = await reservar(cabeceras_transportista, edificio, tracking_ref="ES456", idempotency_key="reserva-1")

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "IDEMPOTENCY_KEY_REUSED", "detail": "La clave ya se usó con otra petición distinta"}
    assert await taquillas(session, edificio) == [("M-01", "BUSY"), ("M-02", "FREE")]
    assert await entregas(session) == [(primera.json()["id"], "SEUR", "ES123")]
    assert await claves(session) == [("SEUR", "reserva-1", fingerprint(cuerpo_de(edificio)), primera.json())]


async def test_clave_nueva_para_un_paquete_ya_reservado_devuelve_409_y_no_guarda_la_clave(
    session: AsyncSession, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F3-05]» Las dos capas protegen cosas distintas: con una clave nueva es una petición nueva, y el índice
    uq_deliveries_active_package la rechaza con 409 DUPLICATE_PACKAGE. La clave nueva no queda guardada (I8):
    la transacción que la registró se deshizo con el error. Solo queda la de la primera reserva.
    """
    edificio = await crear_edificio({"M": 2})
    primera = await reservar(cabeceras_transportista, edificio, idempotency_key="reserva-1")

    respuesta = await reservar(cabeceras_transportista, edificio, idempotency_key="reserva-2")

    assert respuesta.status_code == 409
    assert respuesta.json() == {"code": "DUPLICATE_PACKAGE", "detail": "Este paquete ya tiene una reserva activa"}
    assert await claves(session) == [("SEUR", "reserva-1", fingerprint(cuerpo_de(edificio)), primera.json())]


async def test_sin_idempotency_key_devuelve_422(
    client: AsyncClient, session: AsyncSession, crear_edificio: CrearEdificio, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F3-06]» Sin la cabecera Idempotency-Key, la reserva es un 422 VALIDATION_ERROR y no ocupa ninguna taquilla."""
    edificio = await crear_edificio({"M": 1})

    respuesta = await client.post("/v1/deliveries", json=cuerpo_de(edificio), headers=cabeceras_transportista)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": "Idempotency-Key: Field required"}
    assert await taquillas(session, edificio) == [("M-01", "FREE")]


async def test_sin_clave_de_api_devuelve_401_aunque_falte_idempotency_key(
    client: AsyncClient, crear_edificio: CrearEdificio
) -> None:
    """
    «[F3-06]» Sin clave de API y sin Idempotency-Key la respuesta es 401, no 422: la autenticación se comprueba
    antes que la cabecera. Quien no se identifica no recibe detalles de validación.
    """
    edificio = await crear_edificio({"M": 1})

    respuesta = await client.post("/v1/deliveries", json=cuerpo_de(edificio))

    assert respuesta.status_code == 401
    assert respuesta.json() == {"code": "UNAUTHENTICATED", "detail": "Falta la clave de API o no es válida"}
