# Alta de edificios por la API: respuesta, fila guardada y validación del nombre.
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.xfail(strict=True, reason="el alta de edificios todavía no está implementada")
async def test_operador_crea_edificio_con_el_nombre_recortado(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str]
) -> None:
    """
    «[F1-05]» El operador crea un edificio: 201 con id y name, sin los espacios de los extremos.
    El id es un UUID v7 generado por la aplicación, y la fila queda guardada (la transacción se confirmó).
    """
    respuesta = await client.post("/v1/buildings", json={"name": "  Edificio Sol  "}, headers=cabeceras_operador)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo == {"id": cuerpo["id"], "name": "Edificio Sol"}
    assert uuid.UUID(cuerpo["id"]).version == 7

    filas = (await session.execute(text("SELECT id, name FROM buildings"))).all()
    assert [(str(id_), name) for id_, name in filas] == [(cuerpo["id"], "Edificio Sol")]


@pytest.mark.parametrize("nombre", ["", "   "], ids=["vacio", "solo-espacios"])
async def test_nombre_vacio_devuelve_422(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str], nombre: str
) -> None:
    """«[F1-05]» Un nombre vacío (también tras recortar los espacios) es 422 VALIDATION_ERROR y no crea nada."""
    respuesta = await client.post("/v1/buildings", json={"name": nombre}, headers=cabeceras_operador)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": "name: String should have at least 1 character"}
    assert await session.scalar(text("SELECT count(*) FROM buildings")) == 0
