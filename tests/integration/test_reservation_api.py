# Reservar por la API: asignación de taquilla, errores y paquetes duplicados.
import uuid
from collections.abc import Awaitable, Callable

from httpx import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Los ayudantes del conftest: crear_edificio({"M": 2}) y reservar(cabeceras, edificio, ...)
type CrearEdificio = Callable[[dict[str, int]], Awaitable[str]]
type Reservar = Callable[..., Awaitable[Response]]


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
