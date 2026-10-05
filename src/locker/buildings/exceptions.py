# Errores de dominio de edificios. Solo heredan de la familia que les corresponde.
import uuid

from locker.core.exceptions import NotFoundError


class BuildingNotFoundError(NotFoundError):
    """El edificio pedido no existe."""

    def __init__(self, building_id: uuid.UUID) -> None:
        super().__init__(f"Edificio {building_id} no encontrado")
        self.building_id = building_id
