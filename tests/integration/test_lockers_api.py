# Alta de taquillas por la API: etiquetas generadas por talla, validación y edificio inexistente.
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def crear_edificio(client: AsyncClient, cabeceras: dict[str, str]) -> str:
    """Crea un edificio por la API y devuelve su id."""
    respuesta = await client.post("/v1/buildings", json={"name": "Edificio Sol"}, headers=cabeceras)
    assert respuesta.status_code == 201
    id_edificio: str = respuesta.json()["id"]
    return id_edificio


async def dar_de_alta(client: AsyncClient, cabeceras: dict[str, str], edificio: str, cuerpo: dict[str, Any]) -> list[str]:
    """Da de alta taquillas, comprueba que todas salen libres y de la talla pedida, y devuelve sus etiquetas."""
    respuesta = await client.post(f"/v1/buildings/{edificio}/lockers", json=cuerpo, headers=cabeceras)
    assert respuesta.status_code == 201
    taquillas = respuesta.json()["lockers"]
    for taquilla in taquillas:
        assert taquilla == {"id": taquilla["id"], "label": taquilla["label"], "size": cuerpo["size"], "status": "FREE"}
        assert uuid.UUID(taquilla["id"]).version == 7
    return [taquilla["label"] for taquilla in taquillas]


async def test_alta_de_taquillas_genera_etiquetas_consecutivas_por_talla(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str]
) -> None:
    """
    «[F1-06]» Cada alta continúa la numeración de su talla en ese edificio: con quantity > 1 salen varias
    consecutivas, y cada talla lleva su propio contador (S-01 convive con M-01). quantity vale 1 por defecto.
    """
    edificio = await crear_edificio(client, cabeceras_operador)

    assert await dar_de_alta(client, cabeceras_operador, edificio, {"size": "M", "quantity": 3}) == ["M-01", "M-02", "M-03"]
    assert await dar_de_alta(client, cabeceras_operador, edificio, {"size": "M", "quantity": 2}) == ["M-04", "M-05"]
    assert await dar_de_alta(client, cabeceras_operador, edificio, {"size": "S"}) == ["S-01"]

    # Otro edificio empieza su propia numeración
    otro = await crear_edificio(client, cabeceras_operador)
    assert await dar_de_alta(client, cabeceras_operador, otro, {"size": "M", "quantity": 1}) == ["M-01"]

    # Lo que devolvió la API es lo que quedó guardado
    filas = await session.execute(
        text("SELECT label, size, status FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio}
    )
    assert filas.all() == [
        ("M-01", "M", "FREE"),
        ("M-02", "M", "FREE"),
        ("M-03", "M", "FREE"),
        ("M-04", "M", "FREE"),
        ("M-05", "M", "FREE"),
        ("S-01", "S", "FREE"),
    ]


@pytest.mark.parametrize(
    ("cuerpo", "detail"),
    [
        ({"size": "M", "quantity": 0}, "quantity: Input should be greater than or equal to 1"),
        ({"size": "M", "quantity": 101}, "quantity: Input should be less than or equal to 100"),
        ({"size": "XL", "quantity": 1}, "size: Input should be 'S', 'M' or 'L'"),
    ],
    ids=["quantity-0", "quantity-101", "talla-invalida"],
)
async def test_quantity_fuera_de_rango_o_talla_invalida_devuelve_422(
    client: AsyncClient, cabeceras_operador: dict[str, str], cuerpo: dict[str, Any], detail: str
) -> None:
    """«[F1-07]» quantity va de 1 a 100 y la talla es S, M o L: fuera de eso, 422 VALIDATION_ERROR."""
    edificio = await crear_edificio(client, cabeceras_operador)

    respuesta = await client.post(f"/v1/buildings/{edificio}/lockers", json=cuerpo, headers=cabeceras_operador)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": detail}


async def test_alta_en_edificio_inexistente_devuelve_404(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str]
) -> None:
    """«[F1-07]» Si el edificio no existe, 404 NOT_FOUND con su id en el detail, y no se crea ninguna taquilla."""
    inexistente = uuid.uuid7()

    respuesta = await client.post(
        f"/v1/buildings/{inexistente}/lockers", json={"size": "M", "quantity": 2}, headers=cabeceras_operador
    )

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Edificio {inexistente} no encontrado"}
    assert await session.scalar(text("SELECT count(*) FROM lockers")) == 0
