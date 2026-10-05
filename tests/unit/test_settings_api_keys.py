# Validación de API_KEYS al arrancar: la configuración rechaza listas mal formadas antes de servir ninguna petición.
import json
from typing import Any

import pytest
from pydantic import ValidationError

from locker.core.config import Settings

# La URL no se usa: solo hace falta porque DATABASE_URL es obligatoria
URL_CUALQUIERA = "postgresql+asyncpg://x:x@localhost:5432/x"

CLAVE_OPERADOR = "clave-operador-0000000000"
CLAVE_SEUR = "clave-seur-00000000000000"


def crear_settings(monkeypatch: pytest.MonkeyPatch, api_keys: list[dict[str, Any]]) -> Settings:
    """Crea la configuración leyendo API_KEYS del entorno, en JSON de una línea, como la lee la API al arrancar."""
    monkeypatch.setenv("API_KEYS", json.dumps(api_keys))
    return Settings(database_url=URL_CUALQUIERA, _env_file=None)


def test_api_keys_valida_se_lee_del_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """«[F1-01]» Una lista válida se lee del JSON: cada entrada con su clave, su rol y, si es carrier, su nombre."""
    settings = crear_settings(
        monkeypatch,
        [
            {"key": CLAVE_OPERADOR, "role": "operator"},
            {"key": CLAVE_SEUR, "role": "carrier", "name": "SEUR"},
        ],
    )

    leidas = [(entrada.key.get_secret_value(), entrada.role, entrada.name) for entrada in settings.api_keys]
    assert leidas == [(CLAVE_OPERADOR, "operator", None), (CLAVE_SEUR, "carrier", "SEUR")]


@pytest.mark.parametrize(
    "api_keys",
    [
        [{"key": CLAVE_SEUR, "role": "carrier"}],
        [{"key": CLAVE_OPERADOR, "role": "operator"}, {"key": CLAVE_OPERADOR, "role": "carrier", "name": "SEUR"}],
        [{"key": CLAVE_OPERADOR, "role": "admin"}],
        [{"key": "corta-0123456", "role": "operator"}],
        [],
    ],
    ids=["carrier-sin-name", "claves-repetidas", "rol-invalido", "clave-corta", "lista-vacia"],
)
def test_api_keys_invalida_impide_arrancar_sin_mostrar_la_clave(
    monkeypatch: pytest.MonkeyPatch, api_keys: list[dict[str, Any]]
) -> None:
    """
    «[F1-01]» Una API_KEYS mal formada hace fallar la configuración, así que la API no llega a arrancar.
    El mensaje de error no incluye ninguna clave (I9): ese mensaje acaba en los logs del arranque.
    """
    with pytest.raises(ValidationError) as error:
        crear_settings(monkeypatch, api_keys)

    for entrada in api_keys:
        assert entrada["key"] not in str(error.value)
