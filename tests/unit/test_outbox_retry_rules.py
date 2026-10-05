# Reglas de reintento del outbox: cuánto se espera tras cada fallo y cuándo un evento queda muerto. Lógica pura.
from locker.outbox.service import is_dead, retry_delay_seconds


def test_la_espera_se_duplica_en_cada_fallo() -> None:
    """
    «[F5-01]» Con base 2, los fallos 1 a 4 esperan 2, 4, 8 y 16 segundos (A11: unos 30 segundos de caída
    tolerada en total). El primer fallo espera la base, no el doble.
    """
    assert [retry_delay_seconds(fallo, 2) for fallo in (1, 2, 3, 4)] == [2, 4, 8, 16]


def test_con_base_cero_no_se_espera() -> None:
    """«[F5-01]» Con base 0 (la de los tests) la espera es 0 tras cualquier fallo: el evento vuelve a estar vencido."""
    assert [retry_delay_seconds(fallo, 0) for fallo in (1, 2, 3, 4)] == [0, 0, 0, 0]


def test_el_evento_muere_al_alcanzar_el_maximo_y_no_antes() -> None:
    """«[F5-01]» Con un máximo de 5, el evento sigue vivo tras los fallos 1 a 4 y queda muerto en el quinto."""
    assert [is_dead(fallo, 5) for fallo in (1, 2, 3, 4)] == [False, False, False, False]
    assert is_dead(5, 5)
