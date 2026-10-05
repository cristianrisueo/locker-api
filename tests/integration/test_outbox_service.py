# process_next contra PostgreSQL real: envío, cola vacía, eventos no vencidos, fallos, eventos muertos y reenvíos.
# El notificador es el NotificadorFalso (§14.3); todo lo demás es real.
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from locker.deliveries.pickup_code import derive
from locker.outbox.notifier import Notification
from tests.integration.conftest import SECRETO_RECOGIDA, Depositar, Procesar
from tests.integration.notificador_falso import NotificadorFalso


async def eventos(session: AsyncSession) -> list[dict[str, Any]]:
    """Todas las filas de outbox_events, con todas sus columnas, por id (UUID v7: en orden de creación)."""
    filas = await session.execute(text("SELECT * FROM outbox_events ORDER BY id"))
    return [dict(fila._mapping) for fila in filas]


async def test_un_envio_correcto_lleva_el_codigo_y_borra_el_evento(
    session: AsyncSession, procesar: Procesar, depositar: Depositar, notificador: NotificadorFalso
) -> None:
    """
    «[F5-02]» El notificador recibe el aviso completo: el id del evento, la entrega, el destinatario, la taquilla,
    el edificio y el código correcto. El código lo calcula el test con pickup_code.derive y el secreto de los tests,
    no se copia del servicio. Tras el envío, la fila del evento se borra y process_next devuelve True.
    """
    [entrega] = await depositar()
    [evento] = await eventos(session)
    codigo = derive(SECRETO_RECOGIDA, entrega)

    assert await procesar() is True

    assert notificador.recibidas == [
        Notification(
            event_id=evento["id"],
            delivery_id=entrega,
            recipient="vecino@example.com",
            building_name="Edificio Sol",
            locker_label="M-01",
            pickup_code=codigo,
            message=f"Tu paquete está en la taquilla M-01 del edificio Edificio Sol. Tu código de recogida es {codigo}.",
        )
    ]
    assert await eventos(session) == []


async def test_con_la_cola_vacia_devuelve_false(procesar: Procesar, notificador: NotificadorFalso) -> None:
    """«[F5-03]» Sin eventos, process_next devuelve False y no envía nada."""
    assert await procesar() is False
    assert notificador.recibidas == []


async def test_un_evento_que_aun_no_ha_vencido_no_se_toma(
    session: AsyncSession, procesar: Procesar, depositar: Depositar, notificador: NotificadorFalso
) -> None:
    """
    «[F5-03]» Un evento cuyo next_attempt_at está en el futuro (esperando a reintentarse) no se toma: process_next
    devuelve False, no envía nada y la fila queda tal cual (I13).
    """
    await depositar()
    await session.execute(text("UPDATE outbox_events SET next_attempt_at = now() + interval '1 hour'"))
    await session.commit()
    antes = await eventos(session)

    assert await procesar() is False

    assert notificador.recibidas == []
    assert await eventos(session) == antes
