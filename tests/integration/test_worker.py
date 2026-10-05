# Bucle del worker (run), sin señales ni procesos: se para al pedirlo y sobrevive a un error inesperado.
import asyncio
import logging
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.core.config import Settings
from locker.core.database import create_engine, create_session_factory
from locker.outbox.events import DELIVERY_DEPOSITED, delivery_deposited
from locker.outbox.repository import SqlOutboxRepository
from locker.outbox.worker import run
from tests.integration.conftest import AlembicRunner
from tests.integration.notificador_falso import NotificadorFalso


async def cuantos_eventos(session: AsyncSession) -> int:
    """Cuántas filas tiene outbox_events. Cierra la transacción para que la siguiente lectura sea nueva."""
    cuantos = int((await session.execute(text("SELECT count(*) FROM outbox_events"))).scalar_one())
    await session.rollback()
    return cuantos


async def test_el_worker_se_detiene_al_pedirlo_sin_esperar_a_la_pausa(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    notificador: NotificadorFalso,
    ajustes_outbox: Settings,
) -> None:
    """
    «[F5-11]» Con la cola vacía y una pausa de 60 s entre pasadas, el worker se detiene en cuanto se activa el
    evento de parada, sin esperar a que acabe la pausa. Con una pausa que no se pudiera interrumpir (un sleep), el
    bucle seguiría dormido hasta 60 s después y el test fallaría por el plazo de 5 s.
    """
    ajustes = ajustes_outbox.model_copy(update={"outbox_poll_interval_seconds": 60})
    parada = asyncio.Event()
    tarea = asyncio.create_task(run(session_factory, notificador, ajustes, parada))

    try:
        # La consulta del test cede el control: el worker arranca, entra en el bucle y hace su primera pasada.
        # A partir de aquí, el bucle ya ha dejado atrás la comprobación de parada y solo le queda la pausa
        assert await cuantos_eventos(session) == 0
        assert not tarea.done()

        parada.set()
        async with asyncio.timeout(5):
            await tarea
    finally:
        tarea.cancel()

    assert notificador.recibidas == []


async def test_el_worker_sobrevive_a_un_error_inesperado_y_se_recupera(
    bd_migraciones: str,
    alembic: AlembicRunner,
    notificador: NotificadorFalso,
    ajustes_outbox: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    «[F5-11]» Contra una base de datos sin migrar, cada pasada falla (la tabla no existe): el worker lo registra
    en el log y sigue vivo. Al migrar y apuntar un evento, la siguiente pasada lo envía y lo borra, sin reiniciar
    el worker. Es el arranque de Compose, cuando el worker puede llegar antes que las migraciones.
    """
    ajustes = ajustes_outbox.model_copy(update={"database_url": bd_migraciones, "outbox_poll_interval_seconds": 0.1})
    engine = create_engine(ajustes)
    fabrica = create_session_factory(engine)
    parada = asyncio.Event()
    tarea = asyncio.create_task(run(fabrica, notificador, ajustes, parada))

    try:
        # Plazo amplio como red de seguridad: la migración, en un subproceso, tarda unos segundos
        async with asyncio.timeout(30), fabrica() as observador:
            # Espera, sin dormir, a ver el error en el log: cada consulta del observador cede el control al worker
            with caplog.at_level(logging.ERROR, logger="locker.outbox.worker"):
                while not any(r.name == "locker.outbox.worker" for r in caplog.records):
                    assert not tarea.done(), "el worker terminó en vez de registrar el error y seguir"
                    await observador.execute(text("SELECT 1"))
                    await observador.rollback()
            assert not tarea.done()

            # Se migra la base de datos y se apunta una entrega depositada con su evento, a mano
            alembic(bd_migraciones, "upgrade", "head")
            edificio, taquilla, entrega = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
            async with observador.begin():
                await observador.execute(
                    text("INSERT INTO buildings (id, name, country) VALUES (:id, 'Edificio Luna', 'ES')"), {"id": edificio}
                )
                await observador.execute(
                    text("INSERT INTO lockers (id, building_id, label, size, status) VALUES (:id, :b, 'S-01', 'S', 'BUSY')"),
                    {"id": taquilla, "b": edificio},
                )
                await observador.execute(
                    text(
                        "INSERT INTO deliveries (id, locker_id, carrier, tracking_ref, recipient, status, deposited_at) "
                        "VALUES (:id, :l, 'SEUR', 'ES999', 'vecina@example.com', 'DEPOSITED', now())"
                    ),
                    {"id": entrega, "l": taquilla},
                )
                await SqlOutboxRepository(observador).add(DELIVERY_DEPOSITED, delivery_deposited(entrega))

            # El mismo worker, sin reiniciarlo, envía el aviso y vacía la tabla
            while await cuantos_eventos(observador) > 0:
                assert not tarea.done(), "el worker terminó antes de procesar el evento"

            parada.set()
            await tarea
    finally:
        tarea.cancel()
        await engine.dispose()

    assert [aviso.delivery_id for aviso in notificador.recibidas] == [entrega]
