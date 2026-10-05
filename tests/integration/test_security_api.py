# Autenticación por clave de API y roles, contra las rutas reales de /v1.
# La seguridad actúa antes que el endpoint: estos casos no necesitan datos en la base de datos.
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

# Un edificio que no existe: da igual, la petición se corta antes de buscarlo
EDIFICIO = uuid.uuid7()

# Operaciones de /v1 que existen en esta fase: (método, ruta, cuerpo)
OPERACIONES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/v1/buildings", {"name": "Edificio Sol"}),
    ("POST", f"/v1/buildings/{EDIFICIO}/lockers", {"size": "M", "quantity": 1}),
    ("GET", f"/v1/buildings/{EDIFICIO}/capacity", None),
]
IDS_OPERACIONES = ["crear-edificio", "crear-taquillas", "capacidad"]


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), OPERACIONES, ids=IDS_OPERACIONES)
@pytest.mark.parametrize(
    "cabeceras",
    [{}, {"X-API-Key": ""}, {"X-API-Key": "clave-que-no-existe-0000000"}],
    ids=["sin-clave", "clave-vacia", "clave-desconocida"],
)
async def test_sin_clave_o_con_clave_invalida_devuelve_401(
    client: AsyncClient, metodo: str, ruta: str, cuerpo: dict[str, Any] | None, cabeceras: dict[str, str]
) -> None:
    """
    «[F1-03]» Sin clave, o con una que no está en la configuración, toda operación de /v1 responde
    401 UNAUTHENTICATED con el formato común, no con el error por defecto de FastAPI.
    """
    respuesta = await client.request(metodo, ruta, json=cuerpo, headers=cabeceras)

    assert respuesta.status_code == 401
    assert respuesta.json() == {"code": "UNAUTHENTICATED", "detail": "Falta la clave de API o no es válida"}


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), OPERACIONES[:2], ids=IDS_OPERACIONES[:2])
async def test_transportista_no_crea_edificios_ni_taquillas(
    client: AsyncClient,
    cabeceras_transportista: dict[str, str],
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
) -> None:
    """«[F1-04]» Una clave válida con el rol equivocado recibe 403 FORBIDDEN: solo el operador da de alta."""
    respuesta = await client.request(metodo, ruta, json=cuerpo, headers=cabeceras_transportista)

    assert respuesta.status_code == 403
    assert respuesta.json() == {"code": "FORBIDDEN", "detail": "Esta clave no tiene permiso para esta operación"}
