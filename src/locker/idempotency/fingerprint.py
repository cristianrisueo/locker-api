# Huella de una petición: identifica su cuerpo para saber si un reintento es la misma petición.
import hashlib
import json
from typing import Any


def fingerprint(body: dict[str, Any]) -> str:
    """
    Huella del cuerpo de una petición: SHA-256 en hexadecimal de su JSON canónico.
    El cuerpo llega como diccionario (model_dump(mode="json") del schema), así que solo contiene tipos de JSON.
    Canónico: claves ordenadas (el orden de los campos no cambia la huella) y sin espacios entre separadores
    """

    # Escribe el JSON siempre igual para el mismo contenido
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))

    # SHA-256 en hexadecimal: 64 caracteres, lo que cabe en idempotency_keys.request_hash
    return hashlib.sha256(canonical.encode()).hexdigest()
