# Capa de servicio de entregas: reservar una taquilla para un paquete, con su clave de idempotencia.
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.exceptions import BuildingNotFoundError
from locker.buildings.repository import BuildingRepository
from locker.deliveries.repository import DeliveryRepository
from locker.deliveries.schemas import Delivery, ReservationIn
from locker.idempotency.exceptions import IdempotencyKeyReusedError
from locker.idempotency.fingerprint import fingerprint
from locker.idempotency.repository import IdempotencyRepository
from locker.lockers.exceptions import NoLockerAvailableError
from locker.lockers.repository import LockerRepository


class DeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        deliveries: DeliveryRepository,
        lockers: LockerRepository,
        buildings: BuildingRepository,
        idempotency: IdempotencyRepository,
    ) -> None:
        """
        Recibe la sesión de la petición (para abrir la transacción) y los repositorios que la usan:
        el de entregas, el de taquillas, el de edificios y el de claves de idempotencia, que comparten esa misma sesión
        """
        self._session = session
        self._deliveries = deliveries
        self._lockers = lockers
        self._buildings = buildings
        self._idempotency = idempotency

    async def reserve(self, carrier: str, idempotency_key: str, data: ReservationIn) -> Delivery:
        """
        Reserva una taquilla de la talla pedida para el paquete del transportista y crea la entrega en PENDING.
        La clave de idempotencia hace que repetir la misma petición devuelva la misma respuesta, sin reservar otra vez.
        Todo en una transacción: si algo falla, se deshace todo, también la clave (I8), y la taquilla vuelve a quedar libre
        """

        # Crea la transacción: al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            # 1. Calcula la huella del cuerpo, para reconocer la misma petición aunque lleguen los campos en otro orden
            request_hash = fingerprint(data.model_dump(mode="json"))

            # 2. Registra la clave. Si otra petición con la misma clave está en curso, esto espera a que termine.
            # Si la clave ya existía, no se reserva nada: se compara la huella y se devuelve la respuesta guardada
            if not await self._idempotency.add(carrier, idempotency_key, request_hash):
                stored = await self._idempotency.get(carrier, idempotency_key)
                if stored.request_hash != request_hash:
                    raise IdempotencyKeyReusedError

                # Una clave confirmada siempre tiene respuesta: se guarda (paso 6) en la misma transacción que la crea
                assert stored.response_body is not None
                return Delivery.model_validate(stored.response_body)

            # 3. Comprueba que el edificio existe. Sin esto, un edificio inexistente parecería uno sin taquillas
            if not await self._buildings.exists(data.building_id):
                raise BuildingNotFoundError(data.building_id)

            # 4. Ocupa una taquilla libre de esa talla, en una sola sentencia. Si no queda ninguna, 409.
            locker = await self._lockers.allocate(data.building_id, data.size)
            if locker is None:
                raise NoLockerAvailableError

            # 5. Crea la entrega en la taquilla asignada
            delivery = await self._deliveries.add(locker, carrier, data)

            # 6. Guarda la respuesta en la clave: es lo que recibirá un reintento, aunque la entrega cambie después
            await self._idempotency.save_response(carrier, idempotency_key, delivery.model_dump(mode="json"))
            return delivery
