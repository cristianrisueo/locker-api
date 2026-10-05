# Huella del cuerpo de una petición: función pura, sin base de datos.
import hashlib

from locker.idempotency.fingerprint import fingerprint

# Un cuerpo de reserva tal como lo deja model_dump(mode="json"): solo textos
CUERPO = {
    "building_id": "0197f3a0-1c2d-7e55-8b10-4a9d6c3e2f01",
    "size": "M",
    "tracking_ref": "ES123",
    "recipient": "vecino@example.com",
}


def test_el_orden_de_los_campos_no_cambia_la_huella() -> None:
    """
    «[F3-01]» El mismo cuerpo con los campos en otro orden da la misma huella: el JSON se escribe con las
    claves ordenadas. Si no, un cliente que serializa en otro orden parecería otra petición.
    """
    al_reves = dict(reversed(CUERPO.items()))

    assert list(al_reves) != list(CUERPO)
    assert fingerprint(al_reves) == fingerprint(CUERPO)


def test_un_cuerpo_distinto_da_otra_huella() -> None:
    """«[F3-01]» Basta con cambiar un campo (la referencia del paquete) para que la huella sea otra."""
    assert fingerprint({**CUERPO, "tracking_ref": "ES456"}) != fingerprint(CUERPO)


def test_la_huella_es_el_sha256_del_json_canonico() -> None:
    """
    «[F3-01]» La huella es el SHA-256 en hexadecimal (64 caracteres) del JSON con las claves ordenadas y sin
    espacios. Fija el formato: si cambiara, las claves ya guardadas dejarían de reconocer sus reintentos.
    """
    canonico = (
        '{"building_id":"0197f3a0-1c2d-7e55-8b10-4a9d6c3e2f01","recipient":"vecino@example.com",'
        '"size":"M","tracking_ref":"ES123"}'
    )

    assert fingerprint(CUERPO) == hashlib.sha256(canonico.encode()).hexdigest()
