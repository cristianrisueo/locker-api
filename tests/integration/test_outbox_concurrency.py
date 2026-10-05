# Dos workers a la vez sobre el mismo outbox: cada evento se envía una sola vez y nadie espera a nadie (SKIP LOCKED).
import asyncio
from collections.abc import Coroutine
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import AbrirConexiones, Depositar, Procesar, bloqueos_en_espera
from tests.integration.notificador_falso import NotificadorFalso


async def eventos(session: AsyncSession) -> list[dict[str, Any]]:
    """Todas las filas de outbox_events, con todas sus columnas, por id (UUID v7: en orden de creación)."""
    filas = await session.execute(text("SELECT * FROM outbox_events ORDER BY id"))
    return [dict(fila._mapping) for fila in filas]


async def sin_esperar(pasada: Coroutine[Any, Any, bool], observador: AsyncSession) -> bool:
    """
    Lanza una pasada del worker como tarea y comprueba, mientras dura, que no se queda parada en un bloqueo.
    Devuelve lo que devuelve la pasada. Si la ve esperando, la cancela y el test falla en ese momento
    """
    tarea = asyncio.create_task(pasada)
    try:
        while not tarea.done():
            assert await bloqueos_en_espera(observador) == 0, "process_next se quedó esperando al evento bloqueado"
        return tarea.result()
    finally:
        tarea.cancel()


async def test_dos_workers_a_la_vez_envian_cada_evento_una_sola_vez(
    session: AsyncSession,
    procesar: Procesar,
    depositar: Depositar,
    notificador: NotificadorFalso,
    abrir_conexiones: AbrirConexiones,
) -> None:
    """
    «[F5-07]» Dos workers vacían a la vez un outbox con 8 eventos, cada uno con su sesión en cada pasada: cada
    evento se notifica exactamente una vez y la tabla queda vacía. Sin bloqueo al tomar el evento, los dos tomarían
    el mismo y el residente recibiría el aviso dos veces.
    """
    await depositar(8)
    pendientes = [evento["id"] for evento in await eventos(session)]

    async def worker() -> None:
        """Un worker que procesa eventos hasta que no encuentra ninguno libre."""
        while await procesar():
            pass

    # Los dos workers arrancan a la vez en el mismo bucle de eventos, con sus conexiones ya abiertas
    await abrir_conexiones(2)
    await asyncio.gather(worker(), worker())

    assert sorted(aviso.event_id for aviso in notificador.recibidas) == sorted(pendientes)
    assert await eventos(session) == []


async def test_un_evento_bloqueado_por_otro_worker_se_salta_sin_esperar(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    procesar: Procesar,
    depositar: Depositar,
    notificador: NotificadorFalso,
) -> None:
    """
    «[F5-07]» Versión determinista. Otro worker tiene bloqueado el evento más antiguo (A), sin confirmar.
    process_next no lo espera: procesa el siguiente (B) y devuelve True, y la pasada siguiente devuelve False con A
    intacto. Al terminar el otro worker, A vuelve a estar libre y se procesa. Sin SKIP LOCKED, la pasada se quedaría
    esperando a A; sin ningún bloqueo, tomaría A aunque otro worker lo tuviera y lo enviaría por segunda vez.
    """
    await depositar(2)
    evento_a, evento_b = await eventos(session)

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otro, session_factory() as observador:
        # Otro worker toma A y deja la transacción abierta
        await otro.begin()
        await otro.execute(text("SELECT id FROM outbox_events WHERE id = :id FOR UPDATE"), {"id": evento_a["id"]})

        # Se salta A y procesa B
        assert await sin_esperar(procesar(), observador) is True
        assert [aviso.event_id for aviso in notificador.recibidas] == [evento_b["id"]]

        # Solo queda A, que sigue bloqueado: no hay nada que procesar, y A sigue tal cual
        assert await sin_esperar(procesar(), observador) is False
        assert await eventos(session) == [evento_a]

        # El otro worker termina sin haber hecho nada: A vuelve a estar libre
        await otro.rollback()

    assert await procesar() is True
    assert [aviso.event_id for aviso in notificador.recibidas] == [evento_b["id"], evento_a["id"]]
    assert await eventos(session) == []
