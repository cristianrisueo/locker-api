# Capa de servicio del outbox: las reglas de reintento de un aviso que falla.


def retry_delay_seconds(attempts: int, base_seconds: float) -> float:
    """
    Segundos de espera tras el fallo número attempts (el valor de attempts ya incrementado: 1 tras el primer fallo).
    La espera se duplica en cada fallo empezando por la base: base × 2^(attempts − 1). Con la base por defecto (2),
    los fallos 1 a 4 esperan 2, 4, 8 y 16 segundos, unos 30 en total (A11). Con base 0 no se espera nada.
    El exponente es attempts − 1 y no attempts: así el primer fallo espera la base, como dice la secuencia 2, 4, 8 y 16
    """
    return base_seconds * 2.0 ** (attempts - 1)


def is_dead(attempts: int, max_attempts: int) -> bool:
    """
    Si un evento con attempts fallos ha agotado sus intentos: muere al alcanzar el máximo, no antes.
    Un evento muerto se queda en la tabla con next_attempt_at nulo y el worker ya no lo toma
    """
    return attempts >= max_attempts
