# Flujo completo de una entrega contra el sistema desplegado: reservar, depositar y recoger, repartido entre réplicas.
import uuid

import httpx

from locker.core.config import get_settings
from locker.deliveries.pickup_code import derive


def test_reservar_depositar_y_recoger_contra_las_replicas(
    base_urls: list[str], cabeceras_operador: dict[str, str], cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F4-14]» El ciclo de vida completo de una entrega contra el sistema en contenedores, alternando réplicas:
    reservar en api-1, depositar en api-2, consultar en api-1 y recoger en api-2, y la taquilla vuelve a quedar
    libre. El código lo calcula el test con pickup_code.derive y el secreto del .env, el mismo que reciben las
    réplicas; no se lee de ningún log. Prueba que el código no depende de la réplica que lo comprueba.
    """
    assert len(base_urls) >= 2, "Hacen falta al menos dos réplicas en BASE_URLS"
    api_1, api_2 = base_urls[:2]

    # Un edificio nuevo con una taquilla M, creado por el operador
    respuesta = httpx.post(f"{api_1}/v1/buildings", json={"name": "Edificio E2E"}, headers=cabeceras_operador)
    assert respuesta.status_code == 201
    edificio = respuesta.json()["id"]
    respuesta = httpx.post(f"{api_1}/v1/buildings/{edificio}/lockers", json={"size": "M"}, headers=cabeceras_operador)
    assert respuesta.status_code == 201

    # Reservar en api-1. Referencia única por ejecución: la base de datos desplegada conserva las anteriores
    cuerpo = {"building_id": edificio, "size": "M", "tracking_ref": f"E2E-{uuid.uuid4().hex[:8]}", "recipient": "vecino"}
    cabeceras = {**cabeceras_transportista, "Idempotency-Key": str(uuid.uuid4())}
    reserva = httpx.post(f"{api_1}/v1/deliveries", json=cuerpo, headers=cabeceras)
    assert reserva.status_code == 201
    entrega = reserva.json()["id"]

    # Depositar en api-2 y consultar en api-1: las dos réplicas ven la misma entrega
    deposito = httpx.post(f"{api_2}/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista)
    assert deposito.status_code == 200
    consulta = httpx.get(f"{api_1}/v1/deliveries/{entrega}", headers=cabeceras_transportista)
    assert consulta.json() == deposito.json()
    assert consulta.json()["status"] == "DEPOSITED"

    # Recoger en api-2, sin clave de API, con el código derivado del secreto del .env
    codigo = derive(get_settings().pickup_code_secret.get_secret_value(), uuid.UUID(entrega))
    recogida = httpx.post(f"{api_2}/v1/deliveries/{entrega}/pickup", json={"code": codigo})
    assert recogida.status_code == 200
    assert recogida.json()["status"] == "PICKED_UP"
    assert recogida.json()["picked_up_at"] is not None

    # La taquilla vuelve a estar libre
    capacidad = httpx.get(f"{api_1}/v1/buildings/{edificio}/capacity", headers=cabeceras_operador)
    assert capacidad.json() == {"building_id": edificio, "sizes": [{"size": "M", "total": 1, "free": 1}]}
