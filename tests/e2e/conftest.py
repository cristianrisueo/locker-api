# Fixtures de E2E y smoke: peticiones HTTP reales contra un sistema ya desplegado.
# No levantan nada: `make e2e` despliega el sistema en contenedores y `make smoke` apunta a donde le digas.
import os
from collections.abc import Iterator

import httpx
import pytest


def leer_base_urls() -> list[str]:
    """
    Direcciones de las réplicas, separadas por comas en BASE_URLS. Sin ellas se aborta:
    un E2E que se omite en silencio no prueba nada.
    """
    urls = [url.strip() for url in os.environ.get("BASE_URLS", "").split(",") if url.strip()]
    if not urls:
        raise pytest.UsageError("Falta BASE_URLS. Usa `make e2e` o `make smoke BASE_URLS=http://...,http://...`")
    return urls


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Un test que pida base_url (directamente o a través de client) se ejecuta una vez por réplica."""
    if "base_url" in metafunc.fixturenames:
        urls = leer_base_urls()
        metafunc.parametrize("base_url", urls, ids=urls)


@pytest.fixture
def client(base_url: str) -> Iterator[httpx.Client]:
    """Cliente HTTP síncrono contra una réplica: contra un sistema remoto no se gana nada con async."""
    with httpx.Client(base_url=base_url, timeout=5) as c:
        yield c
