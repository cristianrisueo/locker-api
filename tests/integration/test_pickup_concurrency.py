# Recogidas simultáneas de la misma entrega con el código correcto: solo una recoge, la otra recibe 409.
import asyncio
import uuid
from datetime import datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.deliveries.pickup_code import derive
from locker.deliveries.repository import SqlDeliveryRepository
from locker.lockers.repository import SqlLockerRepository
from tests.integration.conftest import SECRETO_RECOGIDA, AbrirConexiones, CrearEdificio, Reservar, bloqueos_en_espera

# Respuesta de una recogida que llega tarde: la entrega ya no está DEPOSITED
CONFLICTO = {"code": "INVALID_STATE", "detail": "La entrega no está en un estado que permita esta operación"}


async def depositar_una(
    client: AsyncClient, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras: dict[str, str]
) -> dict[str, Any]:
    """Una entrega reservada y depositada, lista para recoger: devuelve la entrega de la respuesta del depósito."""
    edificio = await crear_edificio({"M": 1})
    reserva = (await reservar(cabeceras, edificio)).json()
    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras)
    assert respuesta.status_code == 200
    depositada: dict[str, Any] = respuesta.json()
    return depositada


async def estado_en_bd(session: AsyncSession, entrega: str) -> tuple[str, datetime | None, str]:
    """(estado de la entrega, picked_up_at, estado de su taquilla): lo que de verdad hay en la base de datos."""
    fila = (
        await session.execute(
            text(
                "SELECT d.status, d.picked_up_at, l.status AS locker_status "
                "FROM deliveries d JOIN lockers l ON l.id = d.locker_id WHERE d.id = :id"
            ),
            {"id": entrega},
        )
    ).one()
    return fila.status, fila.picked_up_at, fila.locker_status


async def test_dos_recogidas_simultaneas_solo_una_recoge(
    session: AsyncSession,
    client: AsyncClient,
    abrir_conexiones: AbrirConexiones,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-11]» Dos recogidas a la vez con el código correcto, cada una con su sesión: una recibe 200 y la otra 409
    INVALID_STATE. La entrega queda PICKED_UP con la hora de la que ganó, y la taquilla FREE.
    """
    depositada = await depositar_una(client, crear_edificio, reservar, cabeceras_transportista)
    cuerpo = {"code": derive(SECRETO_RECOGIDA, uuid.UUID(depositada["id"]))}
    url = f"/v1/deliveries/{depositada['id']}/pickup"

    # Las dos peticiones se lanzan a la vez en el mismo bucle de eventos, con sus conexiones ya abiertas
    await abrir_conexiones(2)
    respuestas = await asyncio.gather(client.post(url, json=cuerpo), client.post(url, json=cuerpo))

    assert sorted(r.status_code for r in respuestas) == [200, 409]
    ganadora = next(r for r in respuestas if r.status_code == 200)
    perdedora = next(r for r in respuestas if r.status_code == 409)
    assert perdedora.json() == CONFLICTO
    estado, recogida, taquilla = await estado_en_bd(session, depositada["id"])
    assert (estado, taquilla) == ("PICKED_UP", "FREE")
    assert recogida == datetime.fromisoformat(ganadora.json()["picked_up_at"])


async def test_una_recogida_que_espera_a_otra_en_curso_devuelve_409(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-11]» Versión determinista. Otra recogida está en curso: ya ha pasado la entrega a PICKED_UP y ha liberado
    la taquilla, sin confirmar. La recogida por la API pasa las comprobaciones (todavía ve la entrega DEPOSITED) y
    se queda esperando en el UPDATE condicional. Al confirmar la otra, PostgreSQL vuelve a evaluar la condición
    con la fila confirmada, el UPDATE no cambia nada y la recogida responde 409 INVALID_STATE. La entrega conserva
    la hora de la otra recogida y la taquilla se ha liberado una sola vez. Sin «status = 'DEPOSITED'» en el
    UPDATE, esta recogida también cambiaría la fila e intentaría liberar otra vez la taquilla.
    """
    depositada = await depositar_una(client, crear_edificio, reservar, cabeceras_transportista)
    entrega = uuid.UUID(depositada["id"])

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otra, session_factory() as observador:
        # Otra recogida en curso: cambia el estado y libera la taquilla, y deja la transacción abierta
        await otra.begin()
        recogida = await SqlDeliveryRepository(otra).pick_up(entrega)
        assert recogida is not None
        assert await SqlLockerRepository(otra).release(recogida.locker_id)

        # La recogida por la API se lanza como tarea y se espera, sin sleep, hasta verla parada en un bloqueo
        cuerpo = {"code": derive(SECRETO_RECOGIDA, entrega)}
        tarea = asyncio.create_task(client.post(f"/v1/deliveries/{entrega}/pickup", json=cuerpo))
        while await bloqueos_en_espera(observador) == 0:
            assert not tarea.done(), "la recogida terminó sin esperar a la otra recogida en curso"

        # La otra recogida confirma: eso libera la fila de la entrega
        await otra.commit()

        respuesta = await tarea

    assert respuesta.status_code == 409
    assert respuesta.json() == CONFLICTO
    assert await estado_en_bd(session, depositada["id"]) == ("PICKED_UP", recogida.delivery.picked_up_at, "FREE")
