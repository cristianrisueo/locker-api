# Capa de servicio de taquillas: alta de taquillas con etiqueta generada y consulta de capacidad.
from locker.lockers.schemas import Size


def make_label(size: Size, number: int) -> str:
    """Etiqueta de una taquilla: la talla y el número con dos cifras como mínimo (M-03, M-100)."""
    # :02d rellena con ceros a la izquierda hasta dos cifras; con más cifras no recorta nada
    return f"{size}-{number:02d}"
