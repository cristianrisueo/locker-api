# Eventos del outbox: su tipo y su contenido. Es lo único que el resto de la aplicación sabe de un evento.
import uuid

# Tipo del evento que se apunta al depositar un paquete: el worker avisa al residente de que ya puede recogerlo
DELIVERY_DEPOSITED = "delivery.deposited"


def delivery_deposited(delivery_id: uuid.UUID) -> dict[str, str]:
    """
    Contenido (payload) del evento delivery.deposited: solo el id de la entrega, en texto para que quepa en JSON.
    No lleva el código de recogida ni los datos del residente (I7): el worker los obtiene al enviar el aviso
    """
    return {"delivery_id": str(delivery_id)}
