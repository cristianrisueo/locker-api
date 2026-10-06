# Capa de servicio de entregas: reservar una taquilla para un paquete (con su clave de idempotencia), depositarlo,
# consultarlo y recogerlo.
import uuid

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from locker.buildings.exceptions import BuildingNotFoundError
from locker.buildings.repository import BuildingRepository
from locker.deliveries import pickup_code
from locker.deliveries.exceptions import DeliveryNotFoundError, InvalidPickupCodeError, InvalidStateError
from locker.deliveries.repository import DeliveryRepository
from locker.deliveries.schemas import Delivery, ReservationIn
from locker.idempotency.exceptions import IdempotencyKeyReusedError
from locker.idempotency.fingerprint import fingerprint
from locker.idempotency.repository import IdempotencyRepository
from locker.lockers.exceptions import NoLockerAvailableError
from locker.lockers.repository import LockerRepository
from locker.outbox.events import DELIVERY_DEPOSITED, delivery_deposited
from locker.outbox.repository import OutboxRepository


class DeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        deliveries: DeliveryRepository,
        lockers: LockerRepository,
        buildings: BuildingRepository,
        idempotency: IdempotencyRepository,
        outbox: OutboxRepository,
        pickup_code_secret: SecretStr,
        reservation_ttl_seconds: int,
    ) -> None:
        """
        Recibe la sesión de la petición (para abrir la transacción) y los repositorios que la usan: el de entregas,
        el de taquillas, el de edificios, el de claves de idempotencia y el del outbox, que comparten esa misma sesión.
        Y el secreto con el que se comprueba el código de recogida, que sigue siendo un SecretStr hasta que se usa,
        y el plazo de una reserva antes de caducar, en segundos
        """
        self._session = session
        self._deliveries = deliveries
        self._lockers = lockers
        self._buildings = buildings
        self._idempotency = idempotency
        self._outbox = outbox
        self._pickup_code_secret = pickup_code_secret
        self._reservation_ttl_seconds = reservation_ttl_seconds

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

            # 5. Crea la entrega en la taquilla asignada, con su plazo: si no se deposita antes, caducará (§7.13)
            delivery = await self._deliveries.add(locker, carrier, data, self._reservation_ttl_seconds)

            # 6. Guarda la respuesta en la clave: es lo que recibirá un reintento, aunque la entrega cambie después
            await self._idempotency.save_response(carrier, idempotency_key, delivery.model_dump(mode="json"))
            return delivery

    async def deposit(self, carrier: str, delivery_id: uuid.UUID) -> Delivery:
        """
        El transportista deposita el paquete: la entrega pasa de PENDING a DEPOSITED y se apunta el evento que
        avisará al residente. Los dos en una transacción (I6): no existe un depósito sin evento ni un evento sin
        depósito. Depositar otra vez una entrega ya depositada la devuelve tal cual, sin un segundo evento
        """

        # Crea la transacción: al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            # 1. Pasa la entrega a DEPOSITED solo si es de este transportista y está PENDING, en una sola sentencia
            delivery = await self._deliveries.deposit(delivery_id, carrier)

            # 2. Si ha cambiado, apunta el evento en esta misma transacción
            if delivery is not None:
                await self._outbox.add(DELIVERY_DEPOSITED, delivery_deposited(delivery.id))
                return delivery

            # 3. No ha cambiado ninguna fila: se lee la entrega del mismo transportista para saber por qué.
            # No existe, o es de otro -> 404, sin revelar que existe
            current = await self._deliveries.get(delivery_id, carrier)
            if current is None:
                raise DeliveryNotFoundError(delivery_id)

            # Ya recogida -> 409. Si no, ya estaba DEPOSITED (un reintento): se devuelve tal cual, sin otro evento
            if current.status == "PICKED_UP":
                raise InvalidStateError
            return current

    async def get(self, carrier: str, delivery_id: uuid.UUID) -> Delivery:
        """
        El transportista consulta su entrega. Es una lectura simple: no necesita transacción (§7.0).
        No existe, o es de otro transportista -> 404, sin revelar que existe
        """
        delivery = await self._deliveries.get(delivery_id, carrier)
        if delivery is None:
            raise DeliveryNotFoundError(delivery_id)
        return delivery

    async def pick_up(self, delivery_id: uuid.UUID, code: str) -> Delivery:
        """
        El residente recoge su paquete con el código: la entrega pasa de DEPOSITED a PICKED_UP y la taquilla vuelve
        a quedar libre, las dos en una transacción. Las comprobaciones van en este orden (§7.7): existe, estado, código
        """

        # Crea la transacción: al salir del bloque se confirma, y si hay un error se deshace
        async with self._session.begin():
            # 1. La entrega no existe -> 404. Sin filtro de transportista: quien recoge es el residente
            delivery = await self._deliveries.get(delivery_id)
            if delivery is None:
                raise DeliveryNotFoundError(delivery_id)

            # 2. No está depositada (sin depositar, o ya recogida) -> 409. Va antes que el código: a quien no
            # conoce el código no le dice nada nuevo, y a quien lo conoce le explica por qué no puede recoger
            if delivery.status != "DEPOSITED":
                raise InvalidStateError

            # 3. El código no es el derivado de la entrega -> 403, y nada cambia. Se compara en tiempo constante
            if not pickup_code.matches(self._pickup_code_secret.get_secret_value(), delivery_id, code):
                raise InvalidPickupCodeError

            # 4. Pasa la entrega a PICKED_UP solo si sigue DEPOSITED. La lectura del paso 2 no protege de nada:
            # si otra recogida simultánea ganó, este UPDATE no cambia ninguna fila -> 409
            picked_up = await self._deliveries.pick_up(delivery_id)
            if picked_up is None:
                raise InvalidStateError

            # 5. Libera la taquilla, también condicional (BUSY -> FREE). Una entrega DEPOSITED siempre ocupa su
            # taquilla: si no estaba ocupada, algo va muy mal, y el error deshace la transacción entera
            if not await self._lockers.release(picked_up.locker_id):
                raise RuntimeError(f"La taquilla {picked_up.locker_id} de una entrega depositada no estaba ocupada")

            return picked_up.delivery
