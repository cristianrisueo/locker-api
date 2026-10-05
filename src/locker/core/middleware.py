# Middleware ASGI del identificador de petición.
# Un middleware ASGI «puro» (sin BaseHTTPMiddleware) envuelve la app y ve pasar cada mensaje de la respuesta.
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from locker.core.logging import request_id_var


class RequestIdMiddleware:
    """
    Genera un identificador por petición y lo devuelve en la cabecera X-Request-ID.
    Mientras dura la petición lo guarda en request_id_var, así cada línea de log lleva su request_id.
    Siempre lo genera el servidor: no se acepta uno que venga del cliente
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Solo las peticiones HTTP llevan identificador (no los eventos del lifespan)
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # UUID v7: lleva la hora dentro, así los identificadores se ordenan por momento de llegada
        request_id = str(uuid.uuid7())

        async def send_with_request_id(message: Message) -> None:
            # El primer mensaje de la respuesta lleva el código y las cabeceras: se añade la nuestra
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        # Lo guarda para los logs y lo retira al terminar, para que no se filtre a otra petición
        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
