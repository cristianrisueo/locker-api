# Middleware ASGI del identificador de petición.
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestIdMiddleware:
    """Genera un identificador por petición y lo devuelve en la cabecera X-Request-ID."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise NotImplementedError
