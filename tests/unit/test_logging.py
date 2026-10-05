# Comprueba los logs en JSON: el formateador escribe una línea JSON válida con los campos comunes y los extra.
import json
import logging
from datetime import datetime, timedelta

from locker.core.logging import JsonFormatter, request_id_var


def crear_registro(**extra: str) -> logging.LogRecord:
    """Crea un registro como lo haría logger.info("...", extra={...}), sin pasar por ningún handler."""
    return logging.getLogger("locker.prueba").makeRecord(
        "locker.prueba", logging.INFO, __file__, 1, "Paquete %s depositado", ("ES123",), None, extra=extra
    )


def test_formateador_escribe_una_linea_json_con_campos_comunes_y_extras() -> None:
    """
    «[F0-06]» Una línea JSON válida con ts (ISO 8601 en UTC), level, logger, message (ya con sus argumentos),
    request_id (el de la petición en curso) y los campos extra que se pasen.
    """
    token = request_id_var.set("0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d70")
    try:
        linea = JsonFormatter().format(crear_registro(event_id="evt-1", delivery_id="del-1"))
    finally:
        request_id_var.reset(token)

    assert "\n" not in linea
    datos = json.loads(linea)
    # ts es ISO 8601 y está en UTC (desfase cero)
    assert datetime.fromisoformat(datos.pop("ts")).utcoffset() == timedelta(0)
    assert datos == {
        "level": "INFO",
        "logger": "locker.prueba",
        "message": "Paquete ES123 depositado",
        "request_id": "0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d70",
        "event_id": "evt-1",
        "delivery_id": "del-1",
    }


def test_formateador_escribe_request_id_nulo_fuera_de_una_peticion() -> None:
    """«[F0-06]» Fuera de una petición (por ejemplo, en el worker) request_id aparece y es nulo."""
    datos = json.loads(JsonFormatter().format(crear_registro()))

    assert datos["request_id"] is None
