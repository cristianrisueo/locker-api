# Depositar por la API: la transición PENDING → DEPOSITED, el evento del outbox, el depósito repetido y los errores.
import asyncio
import uuid
from datetime import datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.deliveries.repository import SqlDeliveryRepository
from locker.outbox.events import DELIVERY_DEPOSITED, delivery_deposited
from locker.outbox.repository import SqlOutboxRepository
from tests.integration.conftest import CrearEdificio, Reservar, bloqueos_en_espera


async def entrega_en_bd(session: AsyncSession, entrega: str) -> tuple[str, datetime | None]:
    """(estado, deposited_at) de la entrega: lo que de verdad hay en la base de datos."""
    fila = (await session.execute(text("SELECT status, deposited_at FROM deliveries WHERE id = :id"), {"id": entrega})).one()
    return fila.status, fila.deposited_at


async def eventos(session: AsyncSession) -> list[dict[str, Any]]:
    """Todas las filas de outbox_events, con todas sus columnas, por id (UUID v7: en orden de creación)."""
    filas = await session.execute(text("SELECT * FROM outbox_events ORDER BY id"))
    return [dict(fila._mapping) for fila in filas]


async def reservar_una(crear_edificio: CrearEdificio, reservar: Reservar, cabeceras: dict[str, str]) -> dict[str, Any]:
    """Un edificio con una taquilla M y una reserva en ella: devuelve la entrega tal como la respondió la API."""
    edificio = await crear_edificio({"M": 1})
    respuesta = await reservar(cabeceras, edificio)
    assert respuesta.status_code == 201
    reserva: dict[str, Any] = respuesta.json()
    return reserva


async def test_depositar_pasa_la_entrega_a_deposited(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-02]» El transportista dueño deposita su entrega PENDING: 200 con la entrega en DEPOSITED y con
    deposited_at, que es la hora guardada en la base de datos. El resto de la entrega no cambia, y la taquilla
    sigue ocupada (se libera al recoger).
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)

    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)

    assert respuesta.status_code == 200
    entrega = respuesta.json()
    assert entrega == {**reserva, "status": "DEPOSITED", "deposited_at": entrega["deposited_at"]}
    estado, depositada = await entrega_en_bd(session, reserva["id"])
    assert estado == "DEPOSITED"
    assert depositada is not None
    assert datetime.fromisoformat(entrega["deposited_at"]) == depositada
    assert await session.scalar(text("SELECT status FROM lockers")) == "BUSY"


async def test_depositar_apunta_el_evento_delivery_deposited_en_la_misma_transaccion(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-03]» Depositar apunta un evento delivery.deposited cuyo payload es solo el id de la entrega (ni el código
    ni los datos del residente), con id UUID v7 (el event_id), 0 intentos y listo para enviarse. Su
    next_attempt_at es now() igual que deposited_at: now() es la hora de inicio de la transacción, así que solo
    coinciden si el evento se escribió en la misma transacción que el cambio de estado.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)

    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)

    assert respuesta.status_code == 200
    _, depositada = await entrega_en_bd(session, reserva["id"])
    (evento,) = await eventos(session)
    assert evento == {
        "id": evento["id"],
        "type": "delivery.deposited",
        "payload": {"delivery_id": reserva["id"]},
        "attempts": 0,
        "next_attempt_at": depositada,
    }
    assert evento["id"].version == 7


async def test_depositar_dos_veces_devuelve_200_y_un_solo_evento(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-04]» Depositar es idempotente por estado: el segundo depósito (un transportista que reintenta porque no
    recibió la respuesta) da 200 con la entrega tal cual, con el mismo deposited_at, y no apunta otro evento.
    El residente no recibe dos avisos.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)
    primera = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)

    segunda = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert segunda.json() == primera.json()
    assert [evento["payload"] for evento in await eventos(session)] == [{"delivery_id": reserva["id"]}]


async def test_un_deposito_que_espera_a_otro_en_curso_no_apunta_un_segundo_evento(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-04]» Versión determinista de dos depósitos a la vez. Otro depósito de la misma entrega está en curso: ya la
    ha pasado a DEPOSITED y ha apuntado su evento, sin confirmar. El depósito por la API se queda esperando en el
    UPDATE condicional. Al confirmar el otro, PostgreSQL vuelve a evaluar la condición con la fila confirmada, el
    UPDATE no cambia nada y el depósito responde 200 con la entrega del otro, sin apuntar un segundo evento.
    Sin «status = 'PENDING'» en el UPDATE, este lo volvería a aplicar y habría dos eventos.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)
    entrega = uuid.UUID(reserva["id"])

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otra, session_factory() as observador:
        # Otro depósito en curso: cambia el estado y apunta el evento, y deja la transacción abierta
        await otra.begin()
        depositada = await SqlDeliveryRepository(otra).deposit(entrega, "SEUR")
        assert depositada is not None
        await SqlOutboxRepository(otra).add(DELIVERY_DEPOSITED, delivery_deposited(entrega))

        # El depósito por la API se lanza como tarea y se espera, sin sleep, hasta verlo parado en un bloqueo
        tarea = asyncio.create_task(client.post(f"/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista))
        while await bloqueos_en_espera(observador) == 0:
            assert not tarea.done(), "el depósito terminó sin esperar al otro depósito en curso"

        # El otro depósito confirma: eso libera la fila de la entrega
        await otra.commit()

        respuesta = await tarea

    assert respuesta.status_code == 200
    assert respuesta.json() == depositada.model_dump(mode="json")
    assert [evento["payload"] for evento in await eventos(session)] == [{"delivery_id": reserva["id"]}]


async def test_depositar_una_entrega_ajena_devuelve_404_y_no_la_cambia(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    cabeceras_correos: dict[str, str],
) -> None:
    """
    «[F4-05]» Correos Express intenta depositar una entrega de SEUR: 404, igual que si no existiera, para no
    revelar que existe (D11). La entrega sigue PENDING y no se apunta ningún evento.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)

    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_correos)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Entrega {reserva['id']} no encontrada"}
    assert await entrega_en_bd(session, reserva["id"]) == ("PENDING", None)
    assert await eventos(session) == []


async def test_depositar_una_entrega_inexistente_devuelve_404(
    client: AsyncClient, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F4-05]» Una entrega que no existe es un 404 con su id en el detail."""
    entrega = uuid.uuid7()

    respuesta = await client.post(f"/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Entrega {entrega} no encontrada"}


async def test_depositar_una_entrega_recogida_devuelve_409(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
) -> None:
    """
    «[F4-05]» Una entrega ya recogida no se puede depositar: 409 INVALID_STATE, sin volver a DEPOSITED y sin
    apuntar ningún evento.
    """
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)
    # El paquete se deposita y se recoge: se hace por SQL, porque recoger todavía no existe
    await session.execute(text("UPDATE deliveries SET status = 'PICKED_UP', deposited_at = now(), picked_up_at = now()"))
    await session.execute(text("UPDATE lockers SET status = 'FREE'"))
    await session.commit()

    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "code": "INVALID_STATE",
        "detail": "La entrega no está en un estado que permita esta operación",
    }
    assert (await entrega_en_bd(session, reserva["id"]))[0] == "PICKED_UP"
    assert await eventos(session) == []


async def test_el_operador_no_puede_depositar(
    session: AsyncSession,
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    cabeceras_operador: dict[str, str],
) -> None:
    """«[F4-05]» Depositar es cosa del transportista: el operador recibe 403 FORBIDDEN y la entrega no cambia."""
    reserva = await reservar_una(crear_edificio, reservar, cabeceras_transportista)

    respuesta = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_operador)

    assert respuesta.status_code == 403
    assert respuesta.json() == {"code": "FORBIDDEN", "detail": "Esta clave no tiene permiso para esta operación"}
    assert await entrega_en_bd(session, reserva["id"]) == ("PENDING", None)
