# Código de recogida: función pura del secreto y del id de la entrega, sin base de datos. Y su secreto en Settings.
import hashlib
import hmac
import re
import uuid

import pytest
from pydantic import SecretStr, ValidationError

from locker.core.config import ApiKey, Settings
from locker.deliveries.pickup_code import derive, matches

# Secretos de prueba: dos distintos, con la longitud mínima de 32 caracteres
SECRETO = "secreto-de-pruebas-00000000000000"
OTRO_SECRETO = "otro-secreto-de-pruebas-000000000"

# Ids fijos: los resultados no dependen de la ejecución
ENTREGA = uuid.UUID("0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d70")
OTRA_ENTREGA = uuid.UUID("0197f3c2-5b8e-7a41-9c3d-2e6f8a1b4d71")


def test_el_codigo_es_determinista_y_de_seis_cifras() -> None:
    """
    «[F4-01]» El mismo secreto y la misma entrega dan siempre el mismo código, de seis cifras. Como no se guarda,
    el servicio de recogida y el worker tienen que calcular el mismo cada vez.
    """
    codigo = derive(SECRETO, ENTREGA)

    assert derive(SECRETO, ENTREGA) == codigo
    assert re.fullmatch(r"[0-9]{6}", codigo)


def test_el_codigo_conserva_los_ceros_a_la_izquierda() -> None:
    """
    «[F4-01]» Un código por debajo de 100000 se escribe con ceros a la izquierda hasta seis cifras («042137»,
    no «42137»). El id se busca recorriendo ids fijos hasta dar con uno cuyo código empiece por 0.
    """
    ids = (uuid.UUID(int=n) for n in range(1000))
    con_cero = next(entrega for entrega in ids if derive(SECRETO, entrega).startswith("0"))

    codigo = derive(SECRETO, con_cero)
    assert len(codigo) == 6
    assert int(codigo) < 100_000


def test_el_codigo_cambia_con_la_entrega_y_con_el_secreto() -> None:
    """«[F4-01]» Otra entrega con el mismo secreto, o la misma entrega con otro secreto, dan otro código."""
    codigo = derive(SECRETO, ENTREGA)

    assert derive(SECRETO, OTRA_ENTREGA) != codigo
    assert derive(OTRO_SECRETO, ENTREGA) != codigo


def test_el_codigo_es_el_hmac_sha256_del_id_en_seis_cifras() -> None:
    """
    «[F4-01]» Fija la fórmula de §7.9, calculada aquí por separado: HMAC-SHA256 del id (en texto) con el secreto,
    los cuatro primeros bytes como entero big-endian, módulo un millón y con ceros hasta seis cifras.
    Si la fórmula cambiara, los códigos ya enviados a los residentes dejarían de valer.
    """
    digest = hmac.new(SECRETO.encode(), str(ENTREGA).encode(), hashlib.sha256).digest()
    esperado = f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"

    assert derive(SECRETO, ENTREGA) == esperado


def test_matches_acepta_el_codigo_correcto_y_rechaza_otro() -> None:
    """«[F4-01]» matches acepta el código derivado de la entrega y rechaza cualquier otro, aunque esté bien formado."""
    codigo = derive(SECRETO, ENTREGA)
    otro = f"{(int(codigo) + 1) % 1_000_000:06d}"

    assert matches(SECRETO, ENTREGA, codigo)
    assert not matches(SECRETO, ENTREGA, otro)
    assert not matches(OTRO_SECRETO, ENTREGA, codigo)


def crear_settings(secreto: str) -> Settings:
    """Configuración completa con el secreto dado, sin leer ningún .env."""
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost:5432/x",
        api_keys=[ApiKey(key=SecretStr("clave-operador-0000000000"), role="operator")],
        pickup_code_secret=SecretStr(secreto),
        _env_file=None,
    )


def test_settings_rechaza_un_secreto_de_menos_de_32_caracteres() -> None:
    """
    «[F4-01]» Un PICKUP_CODE_SECRET de 31 caracteres hace fallar la configuración, así que la API no arranca,
    y el mensaje no repite el secreto (I9). Con 32 caracteres se acepta.
    """
    corto = "s" * 31

    with pytest.raises(ValidationError) as error:
        crear_settings(corto)

    assert corto not in str(error.value)

    # Con 32 caracteres, la configuración se crea sin error
    crear_settings("s" * 32)
