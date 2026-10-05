# Formato de la etiqueta de una taquilla: función pura, sin base de datos.
import pytest

from locker.lockers.schemas import Size
from locker.lockers.service import make_label


@pytest.mark.parametrize(
    ("talla", "numero", "etiqueta"),
    [("S", 1, "S-01"), ("M", 3, "M-03"), ("L", 12, "L-12"), ("M", 100, "M-100")],
)
def test_etiqueta_es_talla_y_numero_con_dos_cifras_minimo(talla: Size, numero: int, etiqueta: str) -> None:
    """«[F1-02]» La etiqueta es <talla>-<n> con el número en dos cifras como mínimo: a partir de 100, tres."""
    assert make_label(talla, numero) == etiqueta
