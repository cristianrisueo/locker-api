# Alta de taquillas simultánea: el bloqueo del edificio serializa las altas de un mismo edificio.
import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locker.buildings.repository import SqlBuildingRepository
from locker.lockers.repository import SqlLockerRepository
from tests.integration.conftest import AbrirConexiones, CrearEdificio


async def test_dos_altas_simultaneas_de_la_misma_talla_salen_consecutivas(
    client: AsyncClient,
    session: AsyncSession,
    abrir_conexiones: AbrirConexiones,
    cabeceras_operador: dict[str, str],
) -> None:
    """
    «[F1-08]» Dos altas de la misma talla a la vez, cada una con su sesión (la fixture client da una por
    petición): sin el bloqueo, las dos contarían 2 taquillas y las dos intentarían crear M-03. Con el bloqueo,
    la segunda espera a la primera, cuenta 3 y crea M-04. Ninguna falla y no hay duplicados.
    """
    respuesta = await client.post("/v1/buildings", json={"name": "Edificio Sol"}, headers=cabeceras_operador)
    edificio = respuesta.json()["id"]
    ruta = f"/v1/buildings/{edificio}/lockers"
    await client.post(ruta, json={"size": "M", "quantity": 2}, headers=cabeceras_operador)

    # Las dos peticiones se lanzan a la vez en el mismo bucle de eventos, con sus conexiones ya abiertas
    await abrir_conexiones(2)
    primera, segunda = await asyncio.gather(
        client.post(ruta, json={"size": "M", "quantity": 1}, headers=cabeceras_operador),
        client.post(ruta, json={"size": "M", "quantity": 1}, headers=cabeceras_operador),
    )

    assert (primera.status_code, segunda.status_code) == (201, 201)
    etiquetas = [r.json()["lockers"][0]["label"] for r in (primera, segunda)]
    assert sorted(etiquetas) == ["M-03", "M-04"]
    filas = await session.scalars(text("SELECT label FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio})
    assert filas.all() == ["M-01", "M-02", "M-03", "M-04"]


async def bloqueos_en_espera(observador: AsyncSession) -> int:
    """
    Cuántas sesiones de esta base de datos están esperando a un bloqueo, según pg_stat_activity.
    PostgreSQL congela esa vista durante cada transacción: se cierra tras leerla para que la siguiente lectura sea nueva
    """
    consulta = text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
    esperando = int((await observador.execute(consulta)).scalar_one())
    await observador.rollback()
    return esperando


async def test_un_alta_espera_al_bloqueo_del_edificio_y_cuenta_despues(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    crear_edificio: CrearEdificio,
    cabeceras_operador: dict[str, str],
) -> None:
    """
    «[F1-08]» Versión determinista, sin depender de la temporización. Otra alta en curso tiene el edificio
    bloqueado: el alta por la API se queda esperando. La otra crea M-03 y confirma; entonces el alta continúa,
    cuenta 3 y crea M-04.
    Sin el bloqueo, el alta no espera: cuenta 2 y crea M-03 al momento, y el test falla en cuanto la ve terminada.
    """
    edificio = await crear_edificio({"M": 2})
    ruta = f"/v1/buildings/{edificio}/lockers"

    # El plazo es la red de seguridad: si algo se queda esperando para siempre, el test falla en vez de colgarse
    async with asyncio.timeout(10), session_factory() as otra, session_factory() as observador:
        # Otra alta en curso: bloquea el edificio y deja la transacción abierta
        await otra.begin()
        assert await SqlBuildingRepository(otra).lock(uuid.UUID(edificio))

        # El alta por la API se lanza como tarea y se espera, sin sleep, hasta verla parada en un bloqueo
        tarea = asyncio.create_task(client.post(ruta, json={"size": "M", "quantity": 1}, headers=cabeceras_operador))
        while await bloqueos_en_espera(observador) == 0:
            assert not tarea.done(), "el alta terminó sin esperar al bloqueo del edificio"

        # La otra alta crea M-03 y confirma: eso libera el edificio
        await SqlLockerRepository(otra).add_many(uuid.UUID(edificio), "M", ["M-03"])
        await otra.commit()

        respuesta = await tarea

    assert respuesta.status_code == 201
    assert [taquilla["label"] for taquilla in respuesta.json()["lockers"]] == ["M-04"]
    filas = await session.scalars(text("SELECT label FROM lockers WHERE building_id = :id ORDER BY label"), {"id": edificio})
    assert filas.all() == ["M-01", "M-02", "M-03", "M-04"]
