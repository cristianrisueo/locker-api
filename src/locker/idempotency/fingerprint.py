# Huella de una petición: identifica su cuerpo para saber si un reintento es la misma petición.
from typing import Any


def fingerprint(body: dict[str, Any]) -> str:
    """Huella del cuerpo de una petición: SHA-256 en hexadecimal de su JSON canónico."""
    raise NotImplementedError
