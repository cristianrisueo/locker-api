# Alta de taquillas simultánea: el bloqueo del edificio serializa las altas de un mismo edificio.
import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.xfail(strict=True, reason="el alta de taquillas todavía no está implementada")
async def test_dos_altas_simultaneas_de_la_misma_talla_salen_consecutivas(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str]
) -> None:
    """
    «[F1-08]» Dos altas de la misma talla a la vez, cada una con su sesión (la fixture client da una por
    petición): sin el bloqueo, las dos contarían 2 taquillas y las dos intentarían crear M-03. Con el bloqueo,
    la segunda espera a la primera, cuenta 3 y crea M-04. Ninguna falla y no hay duplicados.
    """
    respuesta = await client.post("/v1/buildings", json={"name": "Edificio Sol"}, headers=cabeceras_operador)
    edificio = respuesta.json()["id"]
    ruta = f"/v1/buildings/{edificio}/lockers"
    await client.post(ruta, json={"size": "M", "quantity": 2}, headers=cabeceras_operador)

    # Las dos peticiones se lanzan a la vez en el mismo bucle de eventos
    primera, segunda = await asyncio.gather(
        client.post(ruta, json={"size": "M", "quantity": 1}, headers=cabeceras_operador),
        client.post(ruta, json={"size": "M", "quantity": 1}, headers=cabeceras_operador),
    )

    assert (primera.status_code, segunda.status_code) == (201, 201)
    etiquetas = [r.json()["lockers"][0]["label"] for r in (primera, segunda)]
    assert sorted(etiquetas) == ["M-03", "M-04"]
    filas = await session.scalars(text("SELECT label FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio})
    assert filas.all() == ["M-01", "M-02", "M-03", "M-04"]
