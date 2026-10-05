# Código de recogida: se calcula a partir del secreto del servidor y del id de la entrega, y no se guarda.
# Así no hay nada que filtrar desde la base de datos: sin el secreto, el id de la entrega no dice cuál es el código.
import hashlib
import hmac
import uuid


def derive(secret: str, delivery_id: uuid.UUID) -> str:
    """
    Código de recogida de la entrega: seis cifras, siempre las mismas para el mismo secreto y la misma entrega.
    HMAC-SHA256 con el secreto como clave y el id (en texto) como mensaje; los cuatro primeros bytes del
    resultado, leídos como un entero, se reducen a seis cifras con ceros a la izquierda («042137»)
    """

    # La firma del id con el secreto: 32 bytes que nadie puede calcular sin conocer el secreto
    digest = hmac.new(secret.encode(), str(delivery_id).encode(), hashlib.sha256).digest()

    # Los cuatro primeros bytes como un entero sin signo (big-endian), y de ahí las seis últimas cifras
    number = int.from_bytes(digest[:4], "big") % 1_000_000

    # :06d rellena con ceros a la izquierda: 42137 se escribe «042137», que es lo que recibe el residente
    return f"{number:06d}"


def matches(secret: str, delivery_id: uuid.UUID, candidate: str) -> bool:
    """
    Si el código recibido es el de la entrega. Se compara en tiempo constante (hmac.compare_digest): el tiempo
    de respuesta no revela cuántas cifras se acertaron. Se comparan bytes, como las claves de API (core/security.py)
    """
    return hmac.compare_digest(derive(secret, delivery_id).encode(), candidate.encode())
