# Logs en JSON: Convierte cada registro en un objeto JSON y lo envía a la salida estándar.
# Es decir, formatea los logs de API, Worker y Uvicorn en JSON. Esto hace que se puedan filtrar facilmente.
# configure_logging lo llaman el lifespan de la API y, más adelante, el worker.
import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Identificador de la petición en curso. Lo fija el middleware y lo lee el formateador; None fuera de una petición
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Atributos que todo LogRecord trae de serie. Lo que no esté aquí son los campos extra que se pasan con extra={...}.
# color_message lo añade uvicorn a algunos registros (el mismo mensaje con colores de terminal): no aporta nada
STANDARD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    """Formateador que escribe cada registro como una línea JSON."""

    def format(self, record: logging.LogRecord) -> str:
        # Campos comunes: hora en UTC (ISO 8601), nivel, logger, mensaje con sus argumentos ya sustituidos
        # y el identificador de la petición en curso
        data: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }

        # Campos extra que se pasan al registrar: logger.info("...", extra={"event_id": ...})
        for key, value in vars(record).items():
            if key not in STANDARD_ATTRIBUTES:
                data[key] = value

        # Si el registro trae una excepción (logger.exception), se añade la traza como texto
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)

        # default=str: un valor que JSON no sabe escribir (un UUID, una fecha) se escribe como texto
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    """Envía todos los logs a la salida estándar en JSON, a partir del nivel indicado."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    # El logger raíz recibe todo: se queda con un único handler, el de JSON
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn configura sus loggers con handlers propios en texto plano y sin propagar al raíz.
    # Se les quitan para que sus líneas (arranque, accesos, errores) también salgan en JSON
    for name in ("uvicorn", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
