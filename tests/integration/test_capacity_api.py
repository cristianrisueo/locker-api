# Capacidad de un edificio por talla: total y libres, en orden S, M, L.
import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CrearEdificio


async def test_capacidad_desglosa_total_y_libres_por_talla_en_orden_s_m_l(
    client: AsyncClient, session: AsyncSession, crear_edificio: CrearEdificio, cabeceras_operador: dict[str, str]
) -> None:
    """
    «[F1-09]» La capacidad cuenta, por talla, todas las taquillas y las libres. Las ocupadas se ponen por SQL
    (todavía no hay reservas). Sale en orden S, M, L aunque se dieran de alta en otro, y no cuenta las de
    otros edificios.
    """
    edificio = await crear_edificio({"L": 1, "M": 3, "S": 2})
    await crear_edificio({"M": 5})
    await session.execute(
        text("UPDATE lockers SET status = 'BUSY' WHERE building_id = :id AND label IN ('M-01', 'S-02')"),
        {"id": edificio},
    )
    await session.commit()

    respuesta = await client.get(f"/v1/buildings/{edificio}/capacity", headers=cabeceras_operador)

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "building_id": edificio,
        "sizes": [
            {"size": "S", "total": 2, "free": 1},
            {"size": "M", "total": 3, "free": 2},
            {"size": "L", "total": 1, "free": 1},
        ],
    }


async def test_transportista_consulta_la_capacidad_de_un_edificio_sin_taquillas(
    client: AsyncClient, crear_edificio: CrearEdificio, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F1-10]» Un edificio sin taquillas devuelve sizes vacío, y un transportista también puede consultarla."""
    edificio = await crear_edificio({})

    respuesta = await client.get(f"/v1/buildings/{edificio}/capacity", headers=cabeceras_transportista)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"building_id": edificio, "sizes": []}


async def test_capacidad_de_edificio_inexistente_devuelve_404(
    client: AsyncClient, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F1-10]» Un edificio que no existe da 404 NOT_FOUND, no una lista vacía: no es lo mismo que no tener taquillas."""
    inexistente = uuid.uuid7()

    respuesta = await client.get(f"/v1/buildings/{inexistente}/capacity", headers=cabeceras_transportista)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Edificio {inexistente} no encontrado"}
