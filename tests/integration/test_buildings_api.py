# Alta de edificios por la API: respuesta, fila guardada y validación del nombre.
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.models import BuildingModel
from tests.integration.conftest import restriccion_violada

# Códigos SQLSTATE de PostgreSQL: una fila que incumple un CHECK, y un texto más largo que su columna
CHECK_VIOLATION = "23514"
STRING_DATA_RIGHT_TRUNCATION = "22001"


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


@pytest.mark.xfail(strict=True, reason="la respuesta del edificio todavía no incluye country")
async def test_country_es_opcional_y_por_defecto_es(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str]
) -> None:
    """
    «[F3-11]» country es opcional: sin él, el edificio queda en ES; con él, en el país indicado. La respuesta
    lo devuelve y la fila lo guarda. Un cliente de /v1 que no lo conoce sigue funcionando (§8.5).
    """
    sin_pais = await client.post("/v1/buildings", json={"name": "Edificio Sol"}, headers=cabeceras_operador)
    con_pais = await client.post("/v1/buildings", json={"name": "Edifício Lua", "country": "PT"}, headers=cabeceras_operador)

    assert (sin_pais.status_code, con_pais.status_code) == (201, 201)
    assert sin_pais.json() == {"id": sin_pais.json()["id"], "name": "Edificio Sol", "country": "ES"}
    assert con_pais.json() == {"id": con_pais.json()["id"], "name": "Edifício Lua", "country": "PT"}
    filas = (await session.execute(text("SELECT name, country FROM buildings ORDER BY id"))).all()
    assert [tuple(fila) for fila in filas] == [("Edificio Sol", "ES"), ("Edifício Lua", "PT")]


@pytest.mark.parametrize("pais", ["es", "ESP", "E1", ""], ids=["minusculas", "tres-letras", "con-cifra", "vacio"])
async def test_country_mal_formado_devuelve_422(
    client: AsyncClient, session: AsyncSession, cabeceras_operador: dict[str, str], pais: str
) -> None:
    """«[F3-11]» Un country que no son dos letras mayúsculas es un 422 VALIDATION_ERROR y no crea nada."""
    respuesta = await client.post(
        "/v1/buildings", json={"name": "Edificio Sol", "country": pais}, headers=cabeceras_operador
    )

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": "country: String should match pattern '^[A-Z]{2}$'"}
    assert await session.scalar(text("SELECT count(*) FROM buildings")) == 0


async def insertar_edificio(session: AsyncSession, country: str) -> None:
    """Inserta un edificio directamente en la tabla, sin pasar por la API ni por su validación."""
    await session.execute(insert(BuildingModel).values(name="Edificio Sol", country=country))


@pytest.mark.parametrize("pais", ["es", "E1"], ids=["minusculas", "con-cifra"])
async def test_ck_buildings_country_format_rechaza_un_pais_mal_formado(session: AsyncSession, pais: str) -> None:
    """
    «[F3-11]» En la base de datos, ck_buildings_country_format rechaza lo que no son dos letras mayúsculas,
    aunque se escriba en la tabla por otro camino que la API.
    """
    with pytest.raises(IntegrityError) as error:
        await insertar_edificio(session, pais)

    assert restriccion_violada(error.value) == (CHECK_VIOLATION, "ck_buildings_country_format")


async def test_un_pais_de_tres_letras_no_cabe_en_la_columna(session: AsyncSession) -> None:
    """
    «[F3-11]» ESP no llega al CHECK: la columna es varchar(2) y PostgreSQL lo rechaza antes por longitud
    (SQLSTATE 22001). El plan esperaba que lo rechazara ck_buildings_country_format.
    """
    with pytest.raises(DBAPIError) as error:
        await insertar_edificio(session, "ESP")

    assert getattr(error.value.orig, "sqlstate", None) == STRING_DATA_RIGHT_TRUNCATION
