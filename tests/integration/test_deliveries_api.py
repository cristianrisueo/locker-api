# Consultar una entrega por la API: solo el transportista dueño la ve.
import uuid

from httpx import AsyncClient

from tests.integration.conftest import CrearEdificio, Reservar


async def test_consultar_la_entrega_propia_devuelve_200(
    client: AsyncClient, crear_edificio: CrearEdificio, reservar: Reservar, cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F4-07]» El transportista consulta su entrega y recibe su estado actual, no el de la reserva: tras depositar,
    DEPOSITED con su deposited_at. Es la misma entrega que devolvió el depósito.
    """
    edificio = await crear_edificio({"M": 1})
    reserva = (await reservar(cabeceras_transportista, edificio)).json()
    deposito = await client.post(f"/v1/deliveries/{reserva['id']}/deposit", headers=cabeceras_transportista)
    assert deposito.status_code == 200

    respuesta = await client.get(f"/v1/deliveries/{reserva['id']}", headers=cabeceras_transportista)

    assert respuesta.status_code == 200
    assert respuesta.json() == deposito.json()
    assert respuesta.json()["status"] == "DEPOSITED"


async def test_consultar_una_entrega_ajena_devuelve_404(
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    cabeceras_correos: dict[str, str],
) -> None:
    """
    «[F4-07]» Correos Express no ve una entrega de SEUR: 404, igual que si no existiera (D11). Responder 403
    revelaría que la entrega existe.
    """
    edificio = await crear_edificio({"M": 1})
    reserva = (await reservar(cabeceras_transportista, edificio)).json()

    respuesta = await client.get(f"/v1/deliveries/{reserva['id']}", headers=cabeceras_correos)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Entrega {reserva['id']} no encontrada"}


async def test_consultar_una_entrega_inexistente_devuelve_404(
    client: AsyncClient, cabeceras_transportista: dict[str, str]
) -> None:
    """«[F4-07]» Una entrega que no existe es un 404 con su id en el detail."""
    entrega = uuid.uuid7()

    respuesta = await client.get(f"/v1/deliveries/{entrega}", headers=cabeceras_transportista)

    assert respuesta.status_code == 404
    assert respuesta.json() == {"code": "NOT_FOUND", "detail": f"Entrega {entrega} no encontrada"}


async def test_el_operador_no_puede_consultar_entregas(
    client: AsyncClient,
    crear_edificio: CrearEdificio,
    reservar: Reservar,
    cabeceras_transportista: dict[str, str],
    cabeceras_operador: dict[str, str],
) -> None:
    """«[F4-07]» Consultar una entrega es cosa de su transportista: el operador recibe 403 FORBIDDEN."""
    edificio = await crear_edificio({"M": 1})
    reserva = (await reservar(cabeceras_transportista, edificio)).json()

    respuesta = await client.get(f"/v1/deliveries/{reserva['id']}", headers=cabeceras_operador)

    assert respuesta.status_code == 403
    assert respuesta.json() == {"code": "FORBIDDEN", "detail": "Esta clave no tiene permiso para esta operación"}
