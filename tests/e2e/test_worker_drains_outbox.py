# El worker desplegado envía el aviso de un depósito: su evento desaparece de outbox_events en 10 s como máximo.
import asyncio
import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from locker.core.config import get_settings
from locker.core.database import create_engine


async def eventos_de(conexion: AsyncConnection, entrega: str) -> int:
    """Cuántos eventos de esta entrega quedan en outbox_events. Cierra la transacción: cada lectura es nueva."""
    consulta = text("SELECT count(*) FROM outbox_events WHERE payload->>'delivery_id' = :id")
    cuantos = int((await conexion.execute(consulta, {"id": entrega})).scalar_one())
    await conexion.rollback()
    return cuantos


async def test_el_worker_envia_el_aviso_de_un_deposito(
    base_urls: list[str], cabeceras_operador: dict[str, str], cabeceras_transportista: dict[str, str]
) -> None:
    """
    «[F5-12]» Tras depositar contra el sistema en contenedores, el worker envía el aviso y borra el evento en 10 s
    como máximo. Se espera a que desaparezca el evento de ESTA entrega, no a que la tabla quede vacía: la base de
    datos de desarrollo puede conservar eventos de otras ejecuciones (por ejemplo, muertos). La tabla se consulta
    con la DATABASE_URL del .env, que apunta al PostgreSQL de Compose desde fuera.
    """
    api = base_urls[0]

    # Un edificio con una taquilla M, una reserva y su depósito, que apunta el evento
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
    deposito = httpx.post(f"{api}/v1/deliveries/{entrega}/deposit", headers=cabeceras_transportista)
    assert deposito.status_code == 200

    # Consulta la tabla hasta que el evento desaparece. Aquí sí hay una pausa corta entre consultas: el worker es
    # otro proceso y no hay otra forma de esperarlo. El plazo de 10 s hace fallar el test si no llega a enviarlo
    engine = create_engine(get_settings())
    try:
        async with asyncio.timeout(10), engine.connect() as conexion:
            while await eventos_de(conexion, entrega) > 0:
                await asyncio.sleep(0.2)
    finally:
        await engine.dispose()
