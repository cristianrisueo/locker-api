# Worker del outbox: un proceso aparte, con el mismo código que la API, que envía los avisos pendientes.
# Se arranca con `python -m locker.outbox.worker` (o `make worker`) y se para con Ctrl-C (SIGINT) o SIGTERM.
# Aquí se cablea el proceso: configuración, logs, engine, sesiones, repositorios, notificador y servicio.
import asyncio
import contextlib
import logging
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.core.config import Settings, get_settings
from locker.core.database import create_engine, create_session_factory
from locker.core.logging import configure_logging
from locker.deliveries.repository import SqlDeliveryRepository
from locker.outbox.notifier import LogNotifier, Notifier
from locker.outbox.repository import SqlOutboxRepository
from locker.outbox.service import OutboxService

# Logger del worker: arranque, parada y errores inesperados del bucle
logger = logging.getLogger(__name__)


async def process_one(session_factory: async_sessionmaker[AsyncSession], notifier: Notifier, settings: Settings) -> bool:
    """
    Una pasada: procesa el siguiente evento vencido con una sesión nueva, que se cierra al terminar.
    Devuelve lo que devuelve process_next: False si no había nada que procesar
    """
    async with session_factory() as session:
        service = OutboxService(session, SqlOutboxRepository(session), SqlDeliveryRepository(session), notifier, settings)
        return await service.process_next()


async def pause(stop: asyncio.Event, seconds: float) -> None:
    """
    Espera los segundos indicados o hasta que se pida parar, lo que llegue antes. No es un sleep: si llega la
    parada a mitad de la pausa, vuelve al instante en vez de dormir hasta el final
    """
    # wait_for lanza TimeoutError si se cumple el plazo sin que se pida parar: es el final normal de la pausa
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run(
    session_factory: async_sessionmaker[AsyncSession], notifier: Notifier, settings: Settings, stop: asyncio.Event
) -> None:
    """
    Bucle del worker (§7.10), hasta que se active stop. Si había un evento, va a por el siguiente sin esperar; si
    no había ninguno, hace una pausa de OUTBOX_POLL_INTERVAL_SECONDS. La parada no interrumpe el evento en curso:
    se mira al empezar cada vuelta, y corta la pausa si llega durante ella.
    No conoce las señales ni el proceso: recibe todo lo que necesita, y así se prueba sin lanzar procesos
    """
    while not stop.is_set():
        # Un error inesperado (la base de datos no responde, el esquema aún no está migrado...) se registra y se
        # trata como una vuelta sin eventos: tras la pausa se vuelve a intentar. El worker no muere por él.
        # Los fallos al enviar un aviso no llegan aquí: process_next los apunta en el evento
        try:
            processed = await process_one(session_factory, notifier, settings)
        except Exception:
            logger.exception("Error inesperado al procesar el outbox: se reintenta tras la pausa")
            processed = False

        if not processed:
            await pause(stop, settings.outbox_poll_interval_seconds)


async def main() -> None:
    """
    Arranque del proceso: lee la configuración (si falta una variable obligatoria, no arranca), configura los logs
    en JSON y crea su propio pool de conexiones. SIGINT (Ctrl-C) y SIGTERM (docker compose stop) activan la parada.
    Al terminar el bucle, cierra las conexiones del pool de forma ordenada
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)

    # Las señales solo activan el evento de parada: el bucle termina el evento en curso y sale
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    logger.info("Worker del outbox en marcha")
    try:
        await run(create_session_factory(engine), LogNotifier(), settings, stop)
    finally:
        await engine.dispose()
    logger.info("Worker del outbox detenido")


if __name__ == "__main__":
    asyncio.run(main())
