# El worker desplegado caduca una reserva vencida: la consulta la devuelve EXPIRED en 10 s como máximo.
import asyncio
import uuid

import httpx
from sqlalchemy import text

from locker.core.config import get_settings
from locker.core.database import create_engine


async def test_una_reserva_vencida_caduca_en_el_sistema_desplegado(
    base_urls: list[str], cabeceras_operador: dict[str, str], cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F6-11]» Contra el sistema en contenedores, se reserva y se adelanta el plazo de la reserva por SQL (con la
    DATABASE_URL del .env, que apunta al PostgreSQL de Compose desde fuera, como F5-12). El worker la caduca y la
    consulta por la API la devuelve EXPIRED en 10 s como máximo. Se usa el engine de SQLAlchemy y no asyncpg a secas,
    que no trae información de tipos y no pasa mypy estricto
    """
    api = base_urls[0]

    # Un edificio con una taquilla M y una reserva en ella
    respuesta = httpx.post(f"{api}/v1/buildings", json={"name": "Edificio E2E"}, headers=cabeceras_operador)
    assert respuesta.status_code == 201
    edificio = respuesta.json()["id"]
    respuesta = httpx.post(f"{api}/v1/buildings/{edificio}/lockers", json={"size": "M"}, headers=cabeceras_operador)
    assert respuesta.status_code == 201
    cuerpo = {"building_id": edificio, "size": "M", "tracking_ref": f"E2E-{uuid.uuid4().hex[:8]}", "recipient": "vecino"}
    reserva = httpx.post(
        f"{api}/v1/deliveries", json=cuerpo, headers={**cabeceras_transportista, "Idempotency-Key": str(uuid.uuid4())}
    )
    assert reserva.status_code == 201
    entrega = reserva.json()["id"]

    # Adelanta el plazo de ESTA reserva: no espera 30 minutos ni toca las de otras ejecuciones
    engine = create_engine(get_settings())
    try:
        async with engine.begin() as conexion:
            await conexion.execute(
                text("UPDATE deliveries SET expires_at = now() - interval '1 minute' WHERE id = CAST(:id AS uuid)"),
                {"id": entrega},
            )
    finally:
        await engine.dispose()

    # Consulta la entrega hasta que el worker la caduca. Aquí sí hay una pausa corta entre consultas: el worker es
    # otro proceso y no hay otra forma de esperarlo. El plazo de 10 s hace fallar el test si no llega a caducarla
    async with asyncio.timeout(10):
        while True:
            consulta = httpx.get(f"{api}/v1/deliveries/{entrega}", headers=cabeceras_transportista)
            assert consulta.status_code == 200
            if consulta.json()["status"] == "EXPIRED":
                break
            await asyncio.sleep(0.2)
