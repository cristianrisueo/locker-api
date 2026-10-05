# LogNotifier: el aviso sale como una línea de log JSON, con event_id y delivery_id como campos.
import json
import logging
import uuid

import pytest

from locker.core.logging import JsonFormatter
from locker.outbox.notifier import LogNotifier, Notification

# Ids y código fijos: el código empieza por 0 y no aparece en ningún otro campo del aviso
EVENTO = uuid.UUID("0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d70")
ENTREGA = uuid.UUID("0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d71")
CODIGO = "042137"


def crear_aviso() -> Notification:
    """Un aviso completo, como el que construye process_next."""
    return Notification(
        event_id=EVENTO,
        delivery_id=ENTREGA,
        recipient="vecino@example.com",
        building_name="Edificio Sol",
        locker_label="M-01",
        pickup_code=CODIGO,
        message=f"Tu paquete está en la taquilla M-01 del edificio Edificio Sol. Tu código de recogida es {CODIGO}.",
    )


async def test_log_notifier_escribe_el_aviso_en_una_linea_json(caplog: pytest.LogCaptureFixture) -> None:
    """
    «[F5-10]» LogNotifier escribe un único registro en el logger locker.notifier, de nivel INFO, con el texto del
    aviso como mensaje y event_id y delivery_id como campos. Con el formateador de core/logging.py sale una sola
    línea JSON con esos campos.
    """
    aviso = crear_aviso()

    with caplog.at_level(logging.INFO, logger="locker.notifier"):
        await LogNotifier().send(aviso)

    [registro] = caplog.records
    linea = JsonFormatter().format(registro)
    assert "\n" not in linea
    datos = json.loads(linea)
    datos.pop("ts")
    assert datos == {
        "level": "INFO",
        "logger": "locker.notifier",
        "message": aviso.message,
        "request_id": None,
        "event_id": str(EVENTO),
        "delivery_id": str(ENTREGA),
    }


def test_imprimir_el_aviso_no_muestra_el_codigo() -> None:
    """
    «[F5-10]» repr del aviso (lo que sale si alguien lo imprime o lo registra por error) no contiene el código:
    ni pickup_code ni message, que también lo lleva, aparecen en él. El resto de los campos sí.
    """
    texto = repr(crear_aviso())

    assert CODIGO not in texto
    assert str(EVENTO) in texto
