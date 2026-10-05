# Capacidad de un edificio por talla: total y libres, en orden S, M, L.
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def crear_edificio(client: AsyncClient, cabeceras: dict[str, str], taquillas: dict[str, int]) -> str:
    """Crea un edificio por la API con las taquillas indicadas ({talla: cantidad}) y devuelve su id."""
    respuesta = await client.post("/v1/buildings", json={"name": "Edificio Sol"}, headers=cabeceras)
    id_edificio: str = respuesta.json()["id"]
    for talla, cantidad in taquillas.items():
        alta = await client.post(
            f"/v1/buildings/{id_edificio}/lockers", json={"size": talla, "quantity": cantidad}, headers=cabeceras
        )
        assert alta.status_code == 201
    return id_edificio


@pytest.mark.xfail(strict=True, reason="la capacidad todavía no está implementada")
async def test_capacidad_desglosa_total_y_libres_por_talla_en_orden_s_m_l(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str]
) -> None:
    """
    «[F1-09]» La capacidad cuenta, por talla, todas las taquillas y las libres. Las ocupadas se ponen por SQL
    (todavía no hay reservas). Sale en orden S, M, L aunque se dieran de alta en otro, y no cuenta las de
    otros edificios.
    """
    edificio = await crear_edificio(client, cabeceras_operador, {"L": 1, "M": 3, "S": 2})
    await crear_edificio(client, cabeceras_operador, {"M": 5})
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


@pytest.mark.xfail(strict=True, reason="la capacidad todavía no está implementada")
async def test_transportista_consulta_la_capacidad_de_un_edificio_sin_taquillas(
    client: AsyncClient, cabeceras_operador: dict[str, str], cabeceras_transportista: dict[str, str]
) -> None:
    """«[F1-10]» Un edificio sin taquillas devuelve sizes vacío, y un transportista también puede consultarla."""
    edificio = await crear_edificio(client, cabeceras_operador, {})

    respuesta = await client.get(f"/v1/buildings/{edificio}/capacity", headers=cabeceras_transportista)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"building_id": edificio, "sizes": []}


@pytest.mark.xfail(strict=True, reason="la capacidad todavía no está implementada")
async def test_capacidad_de_edificio_inexistente_devuelve_404(
    client: AsyncClient, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F1-10]» Un edificio que no existe da 404 NOT_FOUND, no una lista vacía: no es lo mismo que no tener taquillas."""
    inexistente = uuid.uuid7()

    respuesta = await client.get(f"/v1/buildings/{inexistente}/capacity", headers=cabeceras_transportista)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Edificio {inexistente} no encontrado"}
