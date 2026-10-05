# Middleware del identificador de petición. Hace lo mismo que el middleware ASGI, pero es más fácil de entender.
# Hereda de BaseHTTPMiddleware: recibe la petición, llama al resto de la app con call_next y retoca la respuesta.
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from locker.core.logging import request_id_var


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Genera un identificador por petición y lo devuelve en la cabecera X-Request-ID.
    Mientras dura la petición lo guarda en request_id_var, así cada línea de log lleva su request_id.
    Siempre lo genera el servidor: no se acepta uno que venga del cliente
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # UUID v7: lleva la hora dentro, así los identificadores se ordenan por momento de llegada
        request_id = str(uuid.uuid7())

        # Lo guarda antes de llamar al resto de la app, para que el endpoint y sus logs lo vean.
        # Lo retira al terminar, para que no se filtre a otra petición
        token = request_id_var.set(request_id)

        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        # Añade el identificador a las cabeceras de la respuesta
        response.headers["X-Request-ID"] = request_id
        return response
