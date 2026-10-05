# Logs en JSON: una línea por registro, con el identificador de la petición en curso.
# configure_logging lo llaman el lifespan de la API y, más adelante, el worker.
import logging
from contextvars import ContextVar

# Identificador de la petición en curso. Lo fija el middleware y lo lee el formateador; None fuera de una petición
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Formateador que escribe cada registro como una línea JSON."""

    def format(self, record: logging.LogRecord) -> str:
        raise NotImplementedError


def configure_logging(level: str) -> None:
    """Envía todos los logs a la salida estándar en JSON, a partir del nivel indicado."""
    raise NotImplementedError
