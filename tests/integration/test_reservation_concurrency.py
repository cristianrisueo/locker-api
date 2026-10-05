# Reservas simultáneas: la asignación en una sola sentencia con SKIP LOCKED reparte taquillas distintas.
import asyncio
import uuid
from collections.abc import Awaitable, Callable

from httpx import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.lockers.repository import SqlLockerRepository

# Los ayudantes del conftest: crear_edificio({"M": 5}) y reservar(cabeceras, edificio, ...)
type CrearEdificio = Callable[[dict[str, int]], Awaitable[str]]
type Reservar = Callable[..., Awaitable[Response]]


async def abrir_conexiones(session_factory: async_sessionmaker[AsyncSession], cuantas: int) -> None:
    """
    Deja el pool con varias conexiones abiertas y libres. Abrir una conexión nueva tarda unos milisegundos:
    sin esto, las primeras peticiones podrían terminar antes de que lleguen las demás, y el test pasaría
    aunque las reservas no se solaparan. El pool guarda como mucho 5 conexiones libres (pool_size por defecto)
    """

    async def usar_una() -> None:
        async with session_factory() as s:
            await s.execute(text("SELECT 1"))

    await asyncio.gather(*(usar_una() for _ in range(cuantas)))


async def test_diez_reservas_simultaneas_para_cinco_taquillas(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F2-06]» 10 reservas a la vez, cada una con su sesión y su paquete, para 5 taquillas libres: exactamente
    5 se quedan con una taquilla (todas distintas) y 5 reciben 409 NO_LOCKER_AVAILABLE. Ninguna taquilla tiene
    dos entregas y no queda ninguna libre.
    """
    edificio = await crear_edificio({"M": 5})

    await abrir_conexiones(session_factory, 5)
    respuestas = await asyncio.gather(
        *(reservar(cabeceras_transportista, edificio, tracking_ref=f"ES{n:03d}") for n in range(10))
    )

    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [201] * 5 + [409] * 5
    rechazos = [r.json() for r in respuestas if r.status_code == 409]
    assert rechazos == [{"code": "NO_LOCKER_AVAILABLE", "detail": "No quedan taquillas de esta talla disponibles"}] * 5
    asignadas = sorted(r.json()["locker_label"] for r in respuestas if r.status_code == 201)
    assert asignadas == ["M-01", "M-02", "M-03", "M-04", "M-05"]
    filas = await session.execute(text("SELECT count(*), count(DISTINCT locker_id) FROM deliveries"))
    assert tuple(filas.one()) == (5, 5)
    libres = await session.scalar(text("SELECT count(*) FROM lockers WHERE status = 'FREE'"))
    assert libres == 0


async def test_una_reserva_no_espera_a_otra_en_curso_salta_su_taquilla(
    session_factory: async_sessionmaker[AsyncSession],
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F2-06]» Lo que aporta SKIP LOCKED: con M-01 bloqueada por otra reserva todavía sin confirmar, una reserva
    nueva no espera a que termine, sino que se salta M-01 y se queda con M-02 al momento.
    Sin SKIP LOCKED el resultado del test anterior sería el mismo (PostgreSQL vuelve a mirar el estado de la fila
    tras esperar y pasa a la siguiente), pero las reservas irían en fila. Aquí se quedaría esperando a la otra
    transacción, que no termina hasta el final del test: el plazo de 5 segundos lo convierte en un fallo.
    """
    edificio = await crear_edificio({"M": 2})

    # Otra reserva en curso: ocupa M-01 en su transacción y la deja abierta (la fila sigue bloqueada)
    async with session_factory() as otra:
        await otra.begin()
        en_curso = await SqlLockerRepository(otra).allocate(uuid.UUID(edificio), "M")
        assert en_curso is not None and en_curso.label == "M-01"

        async with asyncio.timeout(5):
            respuesta = await reservar(cabeceras_transportista, edificio, tracking_ref="ES123")

        await otra.rollback()

    assert respuesta.status_code == 201
    assert respuesta.json()["locker_label"] == "M-02"
