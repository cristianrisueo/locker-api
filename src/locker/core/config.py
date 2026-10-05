# Configuración de la aplicación.
# Dos clases: DatabaseSettings (lo único que necesitan Alembic y los tests de base de datos) y Settings (todo lo demás).
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Settings(DatabaseSettings):
    """
    Configuración completa de la API (y, más adelante, del worker).
    Hereda la de la base de datos, así que se puede pasar donde se pida un DatabaseSettings
    """

    # Nivel mínimo de los logs: DEBUG, INFO, WARNING, ERROR o CRITICAL
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """
    Devuelve la configuración. lru_cache guarda el resultado de la primera llamada
    y lo devuelve en las siguientes, evitando leer el archivo .env varias veces.
    """
    return Settings()
