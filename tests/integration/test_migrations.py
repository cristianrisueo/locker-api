# Migraciones de Alembic. Cada test trabaja en su propia base de datos vacía (bd_migraciones).
# Son genéricos (usan head): cubren también las migraciones de las fases siguientes.
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import NullPool, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.integration.conftest import restriccion_violada

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


# La migración de caducidad (F6-09) tampoco usa head: fija la revisión anterior (crear outbox_events) y la de caducidad
ANTES_DE_CADUCIDAD = "afd946b9bb78"
CADUCIDAD = "34ec214bbb00"

# Código SQLSTATE de PostgreSQL para una fila que incumple un CHECK
CHECK_VIOLATION = "23514"


async def entregas_y_plazos(engine: AsyncEngine) -> dict[uuid.UUID, tuple[str, bool | None]]:
    """
    Estado de cada entrega y si su plazo cae a unos 30 minutos de ahora (None si no tiene plazo).
    La migración calcula el plazo con su propio now(), unos instantes antes que esta consulta: de ahí la ventana
    """
    async with engine.connect() as conn:
        filas = await conn.execute(
            text(
                "SELECT id, status, expires_at > now() + interval '29 minutes' "
                "AND expires_at <= now() + interval '30 minutes' AS a_30_minutos FROM deliveries"
            )
        )
        return {fila.id: (fila.status, fila.a_30_minutos) for fila in filas}


async def columnas_de_deliveries(engine: AsyncEngine) -> list[str]:
    """Nombres de las columnas de deliveries, en el orden de la tabla."""
    async with engine.connect() as conn:
        filas = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'deliveries' ORDER BY ordinal_position"
            )
        )
        return [fila.column_name for fila in filas]


@pytest.mark.xfail(strict=True, reason="la migración de caducidad todavía no existe")
async def test_la_migracion_de_caducidad_da_plazo_a_las_reservas_pendientes(
    bd_migraciones: str, alembic: AlembicRunner
) -> None:
    """
    «[F6-09]» Migración con datos: con una entrega en cada estado anterior a la caducidad, la migración da plazo
    (30 minutos) solo a la PENDING y deja en NULL las demás. Después, el CHECK nuevo rechaza una PENDING sin plazo
    y ck_deliveries_status admite EXPIRED. Al bajar, la EXPIRED pasa a PICKED_UP (pérdida asumida: el CHECK antiguo
    no admite EXPIRED), la columna desaparece y vuelve el CHECK antiguo. Volver a subir funciona.
    Sin el backfill, el CHECK de la contract fallaría con la reserva pendiente que ya existía.
    """
    edificio = uuid.uuid7()
    taquillas = [uuid.uuid7() for _ in range(3)]
    pendiente, depositada, recogida = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    # NullPool: una conexión nueva cada vez, como en F3-10. Tras cambiar las columnas de la tabla, una conexión
    # reutilizada podría fallar por una consulta preparada que ya no corresponde
    engine = create_async_engine(bd_migraciones, poolclass=NullPool)
    try:
        # La versión anterior a la caducidad, con una entrega en cada estado (como las tendría una instalación)
        alembic(bd_migraciones, "upgrade", ANTES_DE_CADUCIDAD)
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO buildings (id, name, country) VALUES (:id, 'Edificio Sol', 'ES')"), {"id": edificio}
            )
            await conn.execute(
                text("INSERT INTO lockers (id, building_id, label, size, status) VALUES (:id, :b, :label, 'M', :status)"),
                [
                    {"id": taquillas[0], "b": edificio, "label": "M-01", "status": "BUSY"},
                    {"id": taquillas[1], "b": edificio, "label": "M-02", "status": "BUSY"},
                    {"id": taquillas[2], "b": edificio, "label": "M-03", "status": "FREE"},
                ],
            )
            await conn.execute(
                text(
                    "INSERT INTO deliveries (id, locker_id, carrier, tracking_ref, recipient, status, deposited_at, "
                    "picked_up_at) VALUES (:id, :l, 'SEUR', :ref, 'vecino@example.com', CAST(:status AS varchar), "
                    "CASE WHEN :status <> 'PENDING' THEN now() END, CASE WHEN :status = 'PICKED_UP' THEN now() END)"
                ),
                [
                    {"id": pendiente, "l": taquillas[0], "ref": "ES1", "status": "PENDING"},
                    {"id": depositada, "l": taquillas[1], "ref": "ES2", "status": "DEPOSITED"},
                    {"id": recogida, "l": taquillas[2], "ref": "ES3", "status": "PICKED_UP"},
                ],
            )

        # Subir: solo la PENDING recibe plazo, de 30 minutos
        alembic(bd_migraciones, "upgrade", CADUCIDAD)
        assert await entregas_y_plazos(engine) == {
            pendiente: ("PENDING", True),
            depositada: ("DEPOSITED", None),
            recogida: ("PICKED_UP", None),
        }

        # El CHECK nuevo rechaza una reserva pendiente sin plazo (en la taquilla libre, para no chocar con los índices)
        with pytest.raises(IntegrityError) as error:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO deliveries (id, locker_id, carrier, tracking_ref, recipient) "
                        "VALUES (:id, :l, 'SEUR', 'ES4', 'vecino@example.com')"
                    ),
                    {"id": uuid.uuid7(), "l": taquillas[2]},
                )
        assert restriccion_violada(error.value) == (CHECK_VIOLATION, "ck_deliveries_pending_has_expiry")

        # ck_deliveries_status admite EXPIRED
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE deliveries SET status = 'EXPIRED' WHERE id = :id"), {"id": pendiente})

        # Bajar: la EXPIRED pasa a PICKED_UP, la columna desaparece y el CHECK antiguo vuelve a rechazar EXPIRED
        alembic(bd_migraciones, "downgrade", ANTES_DE_CADUCIDAD)
        assert "expires_at" not in await columnas_de_deliveries(engine)
        async with engine.connect() as conn:
            estados = await conn.execute(text("SELECT id, status FROM deliveries"))
            assert dict(estados.tuples().all()) == {pendiente: "PICKED_UP", depositada: "DEPOSITED", recogida: "PICKED_UP"}
        with pytest.raises(IntegrityError) as error:
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE deliveries SET status = 'EXPIRED' WHERE id = :id"), {"id": pendiente})
        assert restriccion_violada(error.value) == (CHECK_VIOLATION, "ck_deliveries_status")

        # Volver a subir funciona: ya no hay ninguna PENDING, así que ninguna recibe plazo
        alembic(bd_migraciones, "upgrade", CADUCIDAD)
        assert await entregas_y_plazos(engine) == {
            pendiente: ("PICKED_UP", None),
            depositada: ("DEPOSITED", None),
            recogida: ("PICKED_UP", None),
        }
    finally:
        await engine.dispose()
