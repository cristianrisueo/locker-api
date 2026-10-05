# Capa de servicio del outbox: las reglas de reintento de un aviso que falla.


def retry_delay_seconds(attempts: int, base_seconds: float) -> float:
    """Segundos de espera tras el fallo número attempts."""
    raise NotImplementedError


def is_dead(attempts: int, max_attempts: int) -> bool:
    """Si un evento con attempts fallos ha agotado sus intentos."""
    raise NotImplementedError
