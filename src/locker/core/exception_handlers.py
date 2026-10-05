# Manejo de excepciones para traducir errores a respuestas HTTP.
# Es el único sitio de la aplicación que decide qué código corresponde a cada error.
from fastapi import FastAPI


def register_exception_handlers(app: FastAPI) -> None:
    """Registra en la aplicación un manejador por cada familia de errores."""
    raise NotImplementedError
