# Concurrencia entre réplicas: dos procesos de la API reservan a la vez sobre la misma base de datos.
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx


def test_diez_reservas_repartidas_entre_dos_replicas_para_cinco_taquillas(
    base_urls: list[str], cabeceras_operador: dict[str, str], cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F2-09]» 10 reservas a la vez, la mitad a api-1 y la otra mitad a api-2, para 5 taquillas libres:
    exactamente 5 éxitos, con 5 taquillas distintas, y 5 x 409. La integración (F2-06) prueba la sentencia
    dentro de un proceso; aquí, que la protección está en la base de datos y no en la memoria de una réplica.
    """
    assert len(base_urls) >= 2, "Hacen falta al menos dos réplicas en BASE_URLS"
    api_1, api_2 = base_urls[:2]

    # Un edificio nuevo con 5 taquillas M, creado por el operador
    respuesta = httpx.post(f"{api_1}/v1/buildings", json={"name": "Edificio E2E"}, headers=cabeceras_operador)
    assert respuesta.status_code == 201
    edificio = respuesta.json()["id"]
    cuerpo = {"size": "M", "quantity": 5}
    respuesta = httpx.post(f"{api_1}/v1/buildings/{edificio}/lockers", json=cuerpo, headers=cabeceras_operador)
    assert respuesta.status_code == 201

    # Referencias únicas por ejecución: la base de datos del sistema desplegado conserva las de ejecuciones anteriores
    lote = uuid.uuid4().hex[:8]
    # La barrera hace que los 10 hilos lancen su petición a la vez, en lugar de según se van creando
    barrera = threading.Barrier(10)

    def reservar(n: int) -> httpx.Response:
        replica = api_1 if n % 2 == 0 else api_2
        cuerpo = {"building_id": edificio, "size": "M", "tracking_ref": f"E2E-{lote}-{n}", "recipient": "vecino@example.com"}
        # Cada reserva es una petición distinta: su propia Idempotency-Key, obligatoria desde F3
        cabeceras = {**cabeceras_transportista, "Idempotency-Key": str(uuid.uuid4())}
        barrera.wait()
        return httpx.post(f"{replica}/v1/deliveries", json=cuerpo, headers=cabeceras, timeout=10)

    with ThreadPoolExecutor(max_workers=10) as hilos:
        respuestas = list(hilos.map(reservar, range(10)))

    assert sorted(r.status_code for r in respuestas) == [201] * 5 + [409] * 5
    assert all(r.json()["code"] == "NO_LOCKER_AVAILABLE" for r in respuestas if r.status_code == 409)
    asignadas = sorted(r.json()["locker_label"] for r in respuestas if r.status_code == 201)
    assert asignadas == ["M-01", "M-02", "M-03", "M-04", "M-05"]

    # La capacidad, vista desde la otra réplica, confirma que no queda ninguna libre
    capacidad = httpx.get(f"{api_2}/v1/buildings/{edificio}/capacity", headers=cabeceras_transportista)
    assert capacidad.json() == {"building_id": edificio, "sizes": [{"size": "M", "total": 5, "free": 0}]}
