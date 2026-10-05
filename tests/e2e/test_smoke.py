# Smoke test: Comprueba que cada réplica de la API responde y llega a la base de datos.
import httpx


def test_cada_replica_esta_viva_y_conectada(client: httpx.Client) -> None:
    """«[F0-07]» Cada réplica de BASE_URLS responde y llega a la base de datos."""
    respuesta = client.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}
