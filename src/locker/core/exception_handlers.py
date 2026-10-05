# Manejo de excepciones para traducir errores a respuestas HTTP.
# Es el único sitio de la aplicación que decide qué código corresponde a cada error.
# Todas las respuestas de error tienen la misma forma: {"code": "...", "detail": "..."}
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from locker.core.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthenticatedError,
    UnprocessableError,
)

# Código HTTP de cada familia. Las subclases heredan el de su familia: un dominio nuevo no necesita manejadores
STATUS_BY_FAMILY: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    UnauthenticatedError: status.HTTP_401_UNAUTHORIZED,
    UnprocessableError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ServiceUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def error_response(status_code: int, code: str, detail: str) -> JSONResponse:
    """Construye la respuesta de error con la forma común {code, detail}."""
    return JSONResponse(status_code=status_code, content={"code": code, "detail": detail})


def format_validation_errors(exc: RequestValidationError) -> str:
    """
    Convierte la lista de errores de validación en un texto: «campo: mensaje; campo: mensaje».
    La primera parte de loc dice dónde estaba el dato (body, query, path, header) y se omite;
    si no queda nada (por ejemplo, falta el cuerpo entero), se usa esa primera parte como campo
    """
    partes = []
    for error in exc.errors():
        loc = [str(parte) for parte in error["loc"]]
        campo = ".".join(loc[1:]) or loc[0]
        partes.append(f"{campo}: {error['msg']}")
    return "; ".join(partes)


def register_exception_handlers(app: FastAPI) -> None:
    """Registra en la aplicación un manejador por cada familia de errores y otro para la validación."""

    # Un manejador por familia: cualquier subclase (por ejemplo, un error de un dominio) usa el de su familia
    for family, status_code in STATUS_BY_FAMILY.items():
        # status_code se pasa como valor por defecto para fijarlo en cada vuelta del bucle.
        # Sin eso, todos los manejadores verían el último valor (503)
        async def domain_error_handler(request: Request, exc: Exception, status_code: int = status_code) -> JSONResponse:
            assert isinstance(exc, DomainError)  # FastAPI solo llama aquí con errores de esta familia
            return error_response(status_code, exc.code, exc.detail)

        app.add_exception_handler(family, domain_error_handler)

    # FastAPI devuelve por defecto una lista de errores: se convierte en VALIDATION_ERROR con un detail legible
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "VALIDATION_ERROR", format_validation_errors(exc))
