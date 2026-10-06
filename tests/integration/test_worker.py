# Bucle del worker (run), sin señales ni procesos: se para al pedirlo y sobrevive a un error inesperado.
import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.core.config import Settings
from locker.core.database import create_engine, create_session_factory
from locker.outbox.events import DELIVERY_DEPOSITED, delivery_deposited
from locker.outbox.repository import SqlOutboxRepository
from locker.outbox.worker import run
from tests.integration.conftest import AlembicRunner, CrearEdificio, Depositar, Reservar, vencer
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


# Lo que registra el worker cuando una de sus dos tareas lanza un error inesperado
ERROR_OUTBOX = "Error inesperado al procesar el outbox: se reintenta en la siguiente vuelta"
ERROR_CADUCIDAD = "Error inesperado al caducar reservas: se reintenta en la siguiente vuelta"


async def estado_de(session: AsyncSession, entrega: str) -> tuple[str, str]:
    """(estado de la entrega, estado de su taquilla). Cierra la transacción para que la siguiente lectura sea nueva."""
    consulta = text(
        "SELECT d.status, l.status AS locker_status FROM deliveries d JOIN lockers l ON l.id = d.locker_id "
        "WHERE d.id = CAST(:id AS uuid)"
    )
    fila = (await session.execute(consulta, {"id": entrega})).one()
    await session.rollback()
    return fila.status, fila.locker_status


async def un_aviso_y_una_reserva_vencida(
    session: AsyncSession,
    depositar: Depositar,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras: dict[str, str],
) -> tuple[uuid.UUID, str]:
    """Trabajo para las dos tareas del worker: un depósito con su evento y otra reserva con el plazo vencido."""
    (depositada,) = await depositar(1)
    edificio = await crear_edificio({"M": 1})
    respuesta = await reservar(cabeceras, edificio, tracking_ref="ES-VENCIDA")
    assert respuesta.status_code == 201
    vencida: str = respuesta.json()["id"]
    await vencer(session, vencida)
    return depositada, vencida


@asynccontextmanager
async def trigger_que_falla(session_factory: async_sessionmaker[AsyncSession], disparo: str) -> AsyncIterator[None]:
    """
    Un trigger real de PostgreSQL que hace fallar una sentencia (disparo: «BEFORE DELETE ON outbox_events», por
    ejemplo), sin dobles de prueba. Se quita al salir: el TRUNCATE entre tests no borra triggers
    """
    async with session_factory() as s:
        await s.execute(
            text(
                "CREATE FUNCTION fallar_tarea() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'fallo provocado en una tarea del worker'; END $$"
            )
        )
        await s.execute(text(f"CREATE TRIGGER fallar_tarea {disparo} FOR EACH ROW EXECUTE FUNCTION fallar_tarea()"))
        await s.commit()
    try:
        yield
    finally:
        tabla = disparo.split(" ON ")[1].split()[0]
        async with session_factory() as s:
            await s.execute(text(f"DROP TRIGGER fallar_tarea ON {tabla}"))
            await s.execute(text("DROP FUNCTION fallar_tarea()"))
            await s.commit()


@pytest.mark.xfail(strict=True, reason="el bucle del worker todavía no caduca reservas")
async def test_el_worker_envia_avisos_y_caduca_reservas_en_el_mismo_bucle(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    notificador: NotificadorFalso,
    ajustes_outbox: Settings,
    depositar: Depositar,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F6-10]» Con un aviso pendiente y una reserva vencida, el mismo bucle hace las dos cosas: envía el aviso (y
    borra su evento) y caduca la reserva (EXPIRED, con la taquilla FREE), sin reiniciar nada
    """
    depositada, vencida = await un_aviso_y_una_reserva_vencida(
        session, depositar, crear_edificio, reservar, cabeceras_transportista
    )
    ajustes = ajustes_outbox.model_copy(update={"outbox_poll_interval_seconds": 0.05})
    parada = asyncio.Event()
    tarea = asyncio.create_task(run(session_factory, notificador, ajustes, parada))

    try:
        # Espera, sin dormir, a ver hecho el trabajo de las dos tareas: cada consulta cede el control al worker.
        # El plazo es la red de seguridad: si una tarea no llega a hacer su trabajo, el test falla en vez de colgarse
        async with asyncio.timeout(10):
            while (await cuantos_eventos(session), await estado_de(session, vencida)) != (0, ("EXPIRED", "FREE")):
                assert not tarea.done(), "el worker terminó antes de hacer su trabajo"
            parada.set()
            await tarea
    finally:
        tarea.cancel()

    assert [aviso.delivery_id for aviso in notificador.recibidas] == [depositada]


@pytest.mark.xfail(strict=True, reason="el bucle del worker todavía no caduca reservas")
@pytest.mark.parametrize(
    ("disparo", "error"),
    [("BEFORE DELETE ON outbox_events", ERROR_OUTBOX), ("BEFORE UPDATE ON deliveries", ERROR_CADUCIDAD)],
    ids=["falla-el-outbox", "falla-la-caducidad"],
)
async def test_un_error_inesperado_en_una_tarea_no_impide_la_otra(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    notificador: NotificadorFalso,
    ajustes_outbox: Settings,
    depositar: Depositar,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    disparo: str,
    error: str,
) -> None:
    """
    «[F6-10]» Un trigger hace fallar en cada vuelta una de las dos tareas con un error inesperado: borrar el evento
    enviado (outbox) o pasar la reserva a EXPIRED (caducidad). El worker registra el error de esa tarea y sigue
    vivo, y la otra tarea hace su trabajo igualmente. Con las dos tareas en un mismo try, el error de la primera
    impediría la segunda, y el de la segunda haría creer que la primera también había fallado
    """
    depositada, vencida = await un_aviso_y_una_reserva_vencida(
        session, depositar, crear_edificio, reservar, cabeceras_transportista
    )
    ajustes = ajustes_outbox.model_copy(update={"outbox_poll_interval_seconds": 0.05})

    async with trigger_que_falla(session_factory, disparo):
        parada = asyncio.Event()
        tarea = asyncio.create_task(run(session_factory, notificador, ajustes, parada))
        try:
            with caplog.at_level(logging.ERROR, logger="locker.outbox.worker"):
                async with asyncio.timeout(10):
                    # Hecho = el error de la tarea rota registrado, y el trabajo de la otra terminado
                    while True:
                        assert not tarea.done(), "el worker terminó en vez de registrar el error y seguir"
                        errores = {r.getMessage() for r in caplog.records if r.name == "locker.outbox.worker"}
                        if error == ERROR_OUTBOX:
                            hecho = await estado_de(session, vencida) == ("EXPIRED", "FREE")
                        else:
                            hecho = await cuantos_eventos(session) == 0
                        if hecho and errores:
                            break
                    parada.set()
                    await tarea
        finally:
            tarea.cancel()

    # Solo ha fallado la tarea rota, y lo que hizo fallar sigue sin hacer
    assert errores == {error}
    if error == ERROR_OUTBOX:
        assert await cuantos_eventos(session) == 1
    else:
        assert await estado_de(session, vencida) == ("PENDING", "BUSY")
        assert [aviso.delivery_id for aviso in notificador.recibidas] == [depositada]
