# Peticiones idénticas simultáneas: la clave de idempotencia hace que la segunda espere a la primera y reciba su respuesta.
import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.idempotency.fingerprint import fingerprint
from locker.idempotency.repository import SqlIdempotencyRepository
from tests.integration.conftest import AbrirConexiones, CrearEdificio, Reservar, bloqueos_en_espera


async def test_dos_reservas_identicas_a_la_vez_crean_una_sola_entrega(
    session: AsyncSession,
    abrir_conexiones: AbrirConexiones,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F3-04]» Dos peticiones idénticas (misma clave y mismo cuerpo) a la vez, cada una con su sesión: las dos
    reciben 201 con la misma entrega, y solo hay una entrega y una taquilla ocupada. Sin la clave, la segunda
    chocaría con el índice del paquete y recibiría 409 DUPLICATE_PACKAGE.
    """
    edificio = await crear_edificio({"M": 2})

    # Las dos peticiones se lanzan a la vez en el mismo bucle de eventos, con sus conexiones ya abiertas
    await abrir_conexiones(2)
    primera, segunda = await asyncio.gather(
        reservar(cabeceras_transportista, edificio, idempotency_key="reserva-ES123"),
        reservar(cabeceras_transportista, edificio, idempotency_key="reserva-ES123"),
    )

    assert (primera.status_code, segunda.status_code) == (201, 201)
    assert segunda.json() == primera.json()
    assert await session.scalar(text("SELECT count(*) FROM deliveries")) == 1
    estados = await session.scalars(
        text("SELECT status FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio}
    )
    assert estados.all() == ["BUSY", "FREE"]


async def test_una_reserva_identica_espera_a_la_que_esta_en_curso_y_recibe_su_respuesta(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F3-04]» Versión determinista, sin depender de la temporización. Otra reserva en curso tiene la clave
    registrada sin confirmar: la reserva por la API con la misma clave y el mismo cuerpo se queda esperando
    en el INSERT ... ON CONFLICT. La otra guarda su respuesta y confirma; entonces la reserva continúa, ve la
    clave ya confirmada y devuelve exactamente esa respuesta, sin crear ninguna entrega ni ocupar ninguna taquilla.
    Si la clave se buscara con un SELECT previo, la reserva no vería la fila sin confirmar y seguiría adelante.
    """
    edificio = await crear_edificio({"M": 1})
    cuerpo = {"building_id": edificio, "size": "M", "tracking_ref": "ES123", "recipient": "vecino@example.com"}
    # La respuesta de la otra reserva, inventada: una etiqueta que no existe en el edificio la hace inconfundible
    guardada = {
        "id": str(uuid.uuid7()),
        "status": "PENDING",
        "building_id": edificio,
        "locker_label": "M-09",
        "size": "M",
        "carrier": "SEUR",
        "tracking_ref": "ES123",
        "recipient": "vecino@example.com",
        "deposited_at": None,
        "picked_up_at": None,
    }

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otra, session_factory() as observador:
        # Otra reserva en curso: registra la clave con la huella del mismo cuerpo y deja la transacción abierta
        await otra.begin()
        en_curso = SqlIdempotencyRepository(otra)
        assert await en_curso.add("SEUR", "reserva-ES123", fingerprint(cuerpo))

        # La reserva por la API se lanza como tarea y se espera, sin sleep, hasta verla parada en un bloqueo
        tarea = asyncio.create_task(reservar(cabeceras_transportista, edificio, idempotency_key="reserva-ES123"))
        while await bloqueos_en_espera(observador) == 0:
            assert not tarea.done(), "la reserva terminó sin esperar a la clave de la otra reserva"

        # La otra reserva guarda su respuesta y confirma: eso libera la clave
        await en_curso.save_response("SEUR", "reserva-ES123", guardada)
        await otra.commit()

        respuesta = await tarea

    assert respuesta.status_code == 201
    assert respuesta.json() == guardada
    assert await session.scalar(text("SELECT count(*) FROM deliveries")) == 0
    estados = await session.scalars(text("SELECT status FROM lockers WHERE building_id = :id"), {"id": edificio})
    assert estados.all() == ["FREE"]
