# Configuración de la aplicación.
# Dos clases: DatabaseSettings (lo único que necesitan Alembic y los tests de base de datos) y Settings (todo lo demás).
from functools import lru_cache
from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Roles de las claves de API: el operador da de alta edificios y taquillas; el transportista reserva y deposita
type Role = Literal["operator", "carrier"]


class DatabaseSettings(BaseSettings):
    """
    Configuración de la base de datos, validada por Pydantic al arrancar.
    Alembic usa solo esta clase: así una migración no exige variables que no necesita (claves de API, secretos...).
    """

    # Lee automáticamente las variables de entorno desde un archivo .env en la raíz del proyecto.
    # Busca el nombre de la variable en mayúsculas y con guiones bajos, por ejemplo: DATABASE_URL.
    # Si no existe la variable ni tiene valor por defecto, Pydantic lanzará un error al arrancar
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DSN y mostrar consultas SQL en la consola (para depuración)
    database_url: str
    sql_echo: bool = False


class ApiKey(BaseModel):
    """
    Una entrada de API_KEYS: la clave, el rol de quien la usa y, si es transportista, su nombre.
    La clave es un SecretStr: al imprimir la configuración sale como '**********', nunca en claro
    """

    key: SecretStr = Field(min_length=16)  # String de al menos 16 caracteres, es el secreto que identifica a quien llama
    role: Role  # Literal["operator", "carrier"]
    name: str | None = None  # Si es transportista, su nombre. Si es operador, no se usa y puede ser None

    @model_validator(mode="after")
    def carrier_has_name(self) -> Self:
        """
        Regla que se aplica una vez validado. Es decir, cuando se ha leído la clave, el rol y el nombre (si lo hay).
        Un transportista necesita nombre: es el que se guarda en sus entregas.
        Como no tenemos tabla de transportistas el nombre recibido es lo que lo identifica.
        """
        if self.role == "carrier" and not self.name:
            raise ValueError("una clave con rol carrier necesita name")

        return self


class Settings(DatabaseSettings):
    """
    Configuración completa de la API (y, más adelante, del worker).
    Hereda la de la base de datos, así que se puede pasar donde se pida un DatabaseSettings
    """

    # hide_input_in_errors: si la validación falla, el mensaje no repite el valor recibido.
    # Sin esto, un error en API_KEYS escribiría la clave en los logs del arranque.
    # env_file y extra se heredan de DatabaseSettings: pydantic-settings combina ambas configuraciones
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    # Nivel mínimo de los logs: DEBUG, INFO, WARNING, ERROR o CRITICAL
    log_level: str = "INFO"

    # Claves de API, leídas del JSON de una línea de API_KEYS. Obligatoria y con al menos una entrada
    api_keys: list[ApiKey] = Field(min_length=1)

    # Secreto con el que se calcula el código de recogida (deliveries/pickup_code.py). Obligatorio y de al menos
    # 32 caracteres. SecretStr, como las claves de API: nunca sale en claro al imprimir la configuración.
    # No está en DatabaseSettings: migrar no lo necesita
    pickup_code_secret: SecretStr = Field(min_length=32)

    # Outbox: intentos de envío de un aviso antes de dar el evento por muerto, base de la espera entre reintentos
    # (2, 4, 8 y 16 segundos con la base por defecto; 0 en los tests) y pausa del worker cuando no hay eventos
    outbox_max_attempts: int = 5
    outbox_backoff_base_seconds: float = 2
    outbox_poll_interval_seconds: float = 1

    @field_validator("api_keys")
    @classmethod
    def keys_are_unique(cls, api_keys: list[ApiKey]) -> list[ApiKey]:
        """Dos entradas con la misma clave no dirían quién llama: se rechaza al arrancar."""
        keys = [entry.key.get_secret_value() for entry in api_keys]
        if len(set(keys)) != len(keys):
            raise ValueError("hay claves de API repetidas")
        return api_keys


@lru_cache
def get_settings() -> Settings:
    """
    Devuelve la configuración. lru_cache guarda el resultado de la primera llamada
    y lo devuelve en las siguientes, evitando leer el archivo .env varias veces.
    """
    return Settings()
