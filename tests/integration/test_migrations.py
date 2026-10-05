# Migraciones de Alembic. Cada test trabaja en su propia base de datos vacía (bd_migraciones).
# Son genéricos (usan head): cubren también las migraciones de las fases siguientes.
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# La fixture alembic del conftest: alembic(url, *argumentos)
type AlembicRunner = Callable[..., None]


def test_modelos_y_migraciones_coinciden(bd_migraciones: str, alembic: AlembicRunner) -> None:
    """
    «[F1-12]» Tras aplicar todas las migraciones, alembic check no detecta diferencias con los modelos.
    Caza una migración olvidada después de tocar un modelo. Ojo: no compara los CHECK (los cubre F1-11).
    """
    alembic(bd_migraciones, "upgrade", "head")
    alembic(bd_migraciones, "check")


def test_migraciones_bajan_y_suben_en_vacio(bd_migraciones: str, alembic: AlembicRunner) -> None:
    """«[F1-12]» Todas las migraciones se pueden deshacer y volver a aplicar: caza downgrades rotos."""
    alembic(bd_migraciones, "upgrade", "head")
    alembic(bd_migraciones, "downgrade", "base")
    alembic(bd_migraciones, "upgrade", "head")


# La migración con datos (F3-10) no usa head: fija la revisión anterior a country (crear idempotency_keys) y la
# de country. Así sigue probando justo ese paso cuando haya migraciones posteriores (F4)
ANTES_DE_COUNTRY = "1c44625e544d"
COUNTRY = "a9fb76835f0f"


async def edificios(engine: AsyncEngine) -> list[dict[str, Any]]:
    """Todas las filas de buildings, con todas sus columnas, por id (UUID v7: en orden de creación)."""
    async with engine.connect() as conn:
        filas = await conn.execute(text("SELECT * FROM buildings ORDER BY id"))
        return [dict(fila._mapping) for fila in filas]


@pytest.mark.xfail(strict=True, reason="la migración de country todavía es un esqueleto vacío")
async def test_la_migracion_de_country_conserva_los_edificios_y_les_pone_es(
    bd_migraciones: str, alembic: AlembicRunner
) -> None:
    """
    «[F3-10]» Migración con datos: con edificios ya creados antes de que exista country, la migración los
    conserva y les pone ES (expand → backfill → contract). Bajar y volver a subir tampoco pierde ninguno.
    Sin el backfill, el NOT NULL fallaría con los edificios existentes.
    """
    sol, luna = uuid.uuid7(), uuid.uuid7()
    # NullPool: una conexión nueva cada vez. Una conexión reutilizada guarda las consultas preparadas, y tras
    # cambiar las columnas de la tabla, SELECT * fallaría por un plan en caché que ya no corresponde
    engine = create_async_engine(bd_migraciones, poolclass=NullPool)
    try:
        # La versión anterior a country, con dos edificios insertados por SQL (como los tendría una instalación)
        alembic(bd_migraciones, "upgrade", ANTES_DE_COUNTRY)
        async with engine.begin() as conn:
            filas = [{"id": sol, "name": "Edificio Sol"}, {"id": luna, "name": "Edificio Luna"}]
            await conn.execute(text("INSERT INTO buildings (id, name) VALUES (:id, :name)"), filas)

        alembic(bd_migraciones, "upgrade", COUNTRY)
        con_country = [
            {"id": sol, "name": "Edificio Sol", "country": "ES"},
            {"id": luna, "name": "Edificio Luna", "country": "ES"},
        ]
        assert await edificios(engine) == con_country

        # Bajar quita la columna, pero no los edificios
        alembic(bd_migraciones, "downgrade", ANTES_DE_COUNTRY)
        assert await edificios(engine) == [{"id": sol, "name": "Edificio Sol"}, {"id": luna, "name": "Edificio Luna"}]

        # Volver a subir los deja otra vez con ES
        alembic(bd_migraciones, "upgrade", COUNTRY)
        assert await edificios(engine) == con_country
    finally:
        await engine.dispose()
