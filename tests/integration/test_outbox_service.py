# process_next contra PostgreSQL real: envío, cola vacía, eventos no vencidos, fallos, eventos muertos y reenvíos.
# El notificador es el NotificadorFalso (§14.3); todo lo demás es real.
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from locker.core.config import Settings
from locker.core.logging import JsonFormatter
from locker.deliveries.pickup_code import derive
from locker.outbox.notifier import Notification
from tests.integration.conftest import ROOT, SECRETO_RECOGIDA, Depositar, Procesar
from tests.integration.notificador_falso import NotificadorFalso


async def eventos(session: AsyncSession) -> list[dict[str, Any]]:
    """Todas las filas de outbox_events, con todas sus columnas, por id (UUID v7: en orden de creación)."""
    filas = await session.execute(text("SELECT * FROM outbox_events ORDER BY id"))
    return [dict(fila._mapping) for fila in filas]


async def hora_bd(session: AsyncSession) -> datetime:
    """
    La hora de la base de datos (now()). Se cierra la transacción tras leerla: now() es la hora a la que empezó la
    transacción, y la siguiente lectura tiene que ser nueva
    """
    hora: datetime = (await session.execute(text("SELECT now()"))).scalar_one()
    await session.rollback()
    return hora


# El UPDATE que reactiva los eventos muertos, tal como lo documenta el README (§7.10)
REACTIVAR = "UPDATE outbox_events SET attempts = 0, next_attempt_at = now() WHERE next_attempt_at IS NULL;"


def normalizar(texto: str) -> str:
    """El texto con cada tramo de espacios y saltos de línea reducido a un espacio."""
    return " ".join(texto.split())


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


@pytest.mark.xfail(strict=True, reason="F5-04: falta registrar el fallo")
async def test_un_fallo_del_notificador_programa_el_reintento(
    session: AsyncSession,
    procesar: Procesar,
    depositar: Depositar,
    notificador: NotificadorFalso,
    ajustes_outbox: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    «[F5-04]» El notificador falla: process_next devuelve True sin relanzar el error, y el fallo se confirma. El
    evento sigue en la tabla con attempts = 1 y next_attempt_at en el futuro: la hora de la transacción más la
    base (aquí 60 s, para que se vea la espera). El log del fallo lleva el id del evento y el error, nunca el aviso:
    el código de recogida no aparece en ningún registro (I7).
    """
    [entrega] = await depositar()
    [evento] = await eventos(session)
    notificador.fallar = "antes"
    ajustes = ajustes_outbox.model_copy(update={"outbox_backoff_base_seconds": 60})

    # La transacción del worker empieza entre estas dos horas: su now() está entre ellas
    antes = await hora_bd(session)
    with caplog.at_level(logging.DEBUG):
        assert await procesar(ajustes) is True
    despues = await hora_bd(session)

    [fila] = await eventos(session)
    assert (fila["id"], fila["attempts"]) == (evento["id"], 1)
    assert antes + timedelta(seconds=60) <= fila["next_attempt_at"] <= despues + timedelta(seconds=60)
    assert notificador.recibidas == []

    # Cada registro se escribe como en producción (JSON con sus campos extra), no solo su mensaje
    lineas = [json.loads(JsonFormatter().format(registro)) for registro in caplog.records]
    fallos = [linea for linea in lineas if linea["logger"] == "locker.outbox.service"]
    assert [(f["event_id"], f["error"]) for f in fallos] == [
        (str(evento["id"]), "EnvioFallido: fallo provocado al enviar el aviso")
    ]
    codigo = derive(SECRETO_RECOGIDA, entrega)
    for registro in caplog.records:
        assert codigo not in JsonFormatter().format(registro)


@pytest.mark.xfail(strict=True, reason="F5-05: falta el estado muerto")
async def test_cinco_fallos_seguidos_dejan_el_evento_muerto(
    session: AsyncSession, procesar: Procesar, depositar: Depositar, notificador: NotificadorFalso
) -> None:
    """
    «[F5-05]» Con la base a 0, cada fallo deja el evento vencido otra vez. Tras los fallos 1 a 4 sigue vivo; el
    quinto (OUTBOX_MAX_ATTEMPTS) lo deja muerto: attempts = 5 y next_attempt_at nulo. Y process_next ya no lo toma.
    """
    await depositar()
    notificador.fallar = "antes"

    for fallo in range(1, 6):
        assert await procesar() is True
        [fila] = await eventos(session)
        assert fila["attempts"] == fallo
        assert (fila["next_attempt_at"] is None) == (fallo == 5)

    assert await procesar() is False


@pytest.mark.xfail(strict=True, reason="F5-06: falta el estado muerto y el sql en el readme")
async def test_un_evento_muerto_se_reactiva_con_el_update_documentado(
    session: AsyncSession, procesar: Procesar, depositar: Depositar, notificador: NotificadorFalso
) -> None:
    """
    «[F5-06]» Un evento muerto (cinco fallos) se reactiva con el UPDATE que documenta el README, y la siguiente
    pasada lo envía y lo borra. El test comprueba además que ese SQL aparece en el README tal cual (salvo espacios).
    """
    [entrega] = await depositar()
    notificador.fallar = "antes"
    for _ in range(5):
        await procesar()
    assert await procesar() is False

    # Reactivar: el notificador vuelve a funcionar y se ejecuta el UPDATE documentado
    notificador.fallar = None
    await session.execute(text(REACTIVAR))
    await session.commit()

    assert await procesar() is True
    assert [aviso.delivery_id for aviso in notificador.recibidas] == [entrega]
    assert await eventos(session) == []
    assert normalizar(REACTIVAR) in normalizar((ROOT / "README.md").read_text())
