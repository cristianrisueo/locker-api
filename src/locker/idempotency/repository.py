# Repositorio de claves de idempotencia: define la interfaz y su implementación sobre PostgreSQL.
from typing import Any, NamedTuple, Protocol

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from locker.idempotency.models import IdempotencyKeyModel


class StoredRequest(NamedTuple):
    """Lo que se guardó de una petición con una clave: su huella y la respuesta que recibió."""

    request_hash: str
    response_body: dict[str, Any] | None


class IdempotencyRepository(Protocol):
    """Interfaz de acceso a datos. Cualquier clase con estos métodos la cumple."""

    # Registra la clave con la huella de la petición. Devuelve False si la clave ya existía
    async def add(self, carrier: str, key: str, request_hash: str) -> bool: ...

    # Lee lo guardado de una clave que ya existe
    async def get(self, carrier: str, key: str) -> StoredRequest: ...

    # Guarda la respuesta de la petición en su clave
    async def save_response(self, carrier: str, key: str, response_body: dict[str, Any]) -> None: ...


class SqlIdempotencyRepository:
    """Implementación sobre PostgreSQL con SQLAlchemy. Nunca hace commit ni rollback: eso es cosa del servicio."""

    def __init__(self, session: AsyncSession) -> None:
        """Recibe la sesión de la petición, la misma con la que el servicio abre la transacción."""
        self._session = session

    async def add(self, carrier: str, key: str, request_hash: str) -> bool:
        """
        INSERT ... ON CONFLICT (carrier, key) DO NOTHING RETURNING key, con el insert del dialecto de PostgreSQL.
        Si otra transacción todavía sin confirmar ya insertó la misma clave, este INSERT espera a que termine:
        si confirma, no inserta nada (False); si se deshace, inserta la fila (True).
        No se mira antes con un SELECT si la clave existe: la otra transacción todavía no se vería, y las dos
        seguirían adelante. Es la PK la que pone en fila a dos peticiones con la misma clave
        """
        stmt = (
            insert(IdempotencyKeyModel)
            .values(carrier=carrier, key=key, request_hash=request_hash)
            .on_conflict_do_nothing(index_elements=["carrier", "key"])
            .returning(IdempotencyKeyModel.key)
        )

        # Devuelve una fila si ha insertado, y ninguna si la clave ya existía
        return (await self._session.execute(stmt)).first() is not None

    async def get(self, carrier: str, key: str) -> StoredRequest:
        """
        Lee la huella y la respuesta guardadas. Se llama justo después de un add que devolvió False: con READ
        COMMITTED, esta consulta ya ve la fila que confirmó la otra transacción
        """
        stmt = select(IdempotencyKeyModel.request_hash, IdempotencyKeyModel.response_body).where(
            IdempotencyKeyModel.carrier == carrier, IdempotencyKeyModel.key == key
        )
        row = (await self._session.execute(stmt)).one()
        return StoredRequest(row.request_hash, row.response_body)

    async def save_response(self, carrier: str, key: str, response_body: dict[str, Any]) -> None:
        """UPDATE idempotency_keys SET response_body = :respuesta, sobre la clave registrada en esta transacción."""
        stmt = (
            update(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.carrier == carrier, IdempotencyKeyModel.key == key)
            .values(response_body=response_body)
        )
        await self._session.execute(stmt)
