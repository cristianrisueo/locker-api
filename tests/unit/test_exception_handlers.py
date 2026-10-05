# Comprueba la traducción de errores a HTTP con la forma {code, detail}, sobre una app en memoria.
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from locker.core.exception_handlers import register_exception_handlers
from locker.core.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthenticatedError,
    UnprocessableError,
)


class TaquillaAgotadaError(ConflictError):
    """Error de un dominio inventado: la familia de conflicto no tiene código propio, lo pone cada error."""

    code = "NO_LOCKER_AVAILABLE"


class ClaveReutilizadaError(UnprocessableError):
    """Error de un dominio inventado: la familia de 422 tampoco tiene código propio."""

    code = "IDEMPOTENCY_KEY_REUSED"


class CodigoIncorrectoError(ForbiddenError):
    """Error de un dominio inventado que cambia el código de su familia, pero no su HTTP."""

    code = "INVALID_PICKUP_CODE"


def crear_app_que_lanza(error: Exception) -> FastAPI:
    """App en memoria con los manejadores registrados y un endpoint que lanza el error indicado."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/error")
    async def lanzar() -> None:
        raise error

    return app


@pytest.mark.parametrize(
    ("tipo_error", "detail", "estado", "code"),
    [
        (NotFoundError, "Edificio 1 no encontrado", 404, "NOT_FOUND"),
        (TaquillaAgotadaError, "No quedan taquillas de esta talla disponibles", 409, "NO_LOCKER_AVAILABLE"),
        (ForbiddenError, "Esta clave no tiene permiso para esta operación", 403, "FORBIDDEN"),
        (CodigoIncorrectoError, "Código de recogida incorrecto", 403, "INVALID_PICKUP_CODE"),
        (UnauthenticatedError, "Falta la clave de API o no es válida", 401, "UNAUTHENTICATED"),
        (ClaveReutilizadaError, "La clave ya se usó con otra petición distinta", 422, "IDEMPOTENCY_KEY_REUSED"),
        (ServiceUnavailableError, "Base de datos no disponible", 503, "SERVICE_UNAVAILABLE"),
    ],
    ids=["404", "409", "403", "403-codigo-propio", "401", "422", "503"],
)
async def test_cada_familia_de_error_se_traduce_a_su_http_y_a_code_detail(
    tipo_error: type[DomainError], detail: str, estado: int, code: str
) -> None:
    """«[F0-03]» Cada familia llega al cliente con su HTTP y con {code, detail}, también a través de subclases."""
    app = crear_app_que_lanza(tipo_error(detail))

    # La app corre en memoria, dentro del mismo proceso: no hay red ni base de datos
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        respuesta = await client.get("/error")

    assert respuesta.status_code == estado
    assert respuesta.json() == {"code": code, "detail": detail}


class TaquillasIn(BaseModel):
    """Cuerpo de ejemplo para provocar errores de validación."""

    name: str = Field(min_length=1)
    quantity: int


@pytest.mark.parametrize(
    ("cuerpo", "detail"),
    [
        (
            {"name": "", "quantity": "muchas"},
            "name: String should have at least 1 character; "
            "quantity: Input should be a valid integer, unable to parse string as an integer",
        ),
        ({}, "name: Field required; quantity: Field required"),
    ],
    ids=["valores-invalidos", "campos-ausentes"],
)
async def test_error_de_validacion_se_convierte_en_validation_error_con_detail_en_texto(
    cuerpo: dict[str, str], detail: str
) -> None:
    """
    «[F0-04]» FastAPI devuelve por defecto una lista de errores; el manejador central la convierte
    en 422 VALIDATION_ERROR con un detail legible: «campo: mensaje; campo: mensaje».
    """
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/taquillas")
    async def crear(datos: TaquillasIn) -> None:
        return None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        respuesta = await client.post("/taquillas", json=cuerpo)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"code": "VALIDATION_ERROR", "detail": detail}
