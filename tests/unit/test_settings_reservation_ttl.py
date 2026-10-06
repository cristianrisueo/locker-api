# Validación de RESERVATION_TTL_SECONDS al arrancar: el plazo de una reserva es un entero mayor que 0.
import pytest
from pydantic import SecretStr, ValidationError

from locker.core.config import ApiKey, Settings

# La URL no se usa: solo hace falta porque DATABASE_URL es obligatoria
URL_CUALQUIERA = "postgresql+asyncpg://x:x@localhost:5432/x"


def crear_settings() -> Settings:
    """Crea la configuración con lo obligatorio y sin .env: RESERVATION_TTL_SECONDS sale del entorno o del defecto."""
    return Settings(
        database_url=URL_CUALQUIERA,
        api_keys=[ApiKey(key=SecretStr("clave-operador-0000000000"), role="operator")],
        pickup_code_secret=SecretStr("secreto-recogida-0000000000000000"),
        _env_file=None,
    )


@pytest.mark.xfail(strict=True, reason="RESERVATION_TTL_SECONDS todavía no existe")
def test_el_plazo_de_la_reserva_es_de_30_minutos_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    """«[F6-01]» Sin la variable, una reserva caduca a los 1800 segundos (30 minutos, A6)."""
    monkeypatch.delenv("RESERVATION_TTL_SECONDS", raising=False)

    assert crear_settings().reservation_ttl_seconds == 1800


@pytest.mark.xfail(strict=True, reason="RESERVATION_TTL_SECONDS todavía no existe")
def test_el_plazo_de_la_reserva_se_lee_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """«[F6-01]» Un entero mayor que 0 en RESERVATION_TTL_SECONDS se acepta tal cual."""
    monkeypatch.setenv("RESERVATION_TTL_SECONDS", "60")

    assert crear_settings().reservation_ttl_seconds == 60


@pytest.mark.xfail(strict=True, reason="RESERVATION_TTL_SECONDS todavía no existe")
@pytest.mark.parametrize("valor", ["0", "-1", "-1800"], ids=["cero", "menos-uno", "negativo"])
def test_un_plazo_de_reserva_cero_o_negativo_no_arranca(monkeypatch: pytest.MonkeyPatch, valor: str) -> None:
    """
    «[F6-01]» Un plazo de 0 o negativo se rechaza al arrancar: con él, cada reserva nacería ya caducada y el worker
    la liberaría antes de que el transportista pudiera depositar. El error nombra la variable
    """
    monkeypatch.setenv("RESERVATION_TTL_SECONDS", valor)

    with pytest.raises(ValidationError) as error:
        crear_settings()

    assert [e["loc"] for e in error.value.errors()] == [("reservation_ttl_seconds",)]
