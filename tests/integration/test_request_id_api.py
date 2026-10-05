# Identificador de petición: toda respuesta lo lleva en X-Request-ID, y es distinto en cada petición.
import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Falta el middleware del identificador de petición")
async def test_toda_respuesta_lleva_un_x_request_id_distinto(client: AsyncClient) -> None:
    """
    «[F0-05]» El middleware genera un UUID v7 por petición y lo devuelve en X-Request-ID, también en las
    respuestas de error (una ruta inexistente da 404 sin pasar por ningún endpoint).
    """
    respuestas = [await client.get("/health"), await client.get("/health"), await client.get("/no-existe")]

    assert [r.status_code for r in respuestas] == [200, 200, 404]
    assert all("x-request-id" in r.headers for r in respuestas)
    identificadores = [uuid.UUID(r.headers["x-request-id"]) for r in respuestas]
    assert all(identificador.version == 7 for identificador in identificadores)
    assert len(set(identificadores)) == 3
