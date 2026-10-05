# Imagen de la aplicación. La misma imagen arranca la API y aplica las migraciones (servicio migrate de
# compose.yml, como paso explícito, nunca al arrancar): solo cambia el comando.
FROM python:3.14.8-slim

# uv, en la misma versión que en local
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /bin/uv

# Compila a bytecode al instalar (arranque más rápido), copia en vez de enlazar desde la caché,
# y usa el Python de la imagen en lugar de descargar otro
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras no cambien pyproject.toml ni uv.lock
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Después el código, las migraciones y su configuración
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev

# Sin privilegios de root en tiempo de ejecución
RUN useradd --system --no-create-home app
USER app

# Añade al PATH el entorno virtual (lo creó uv sync), expone el puerto y arranca la API
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "locker.main:app", "--host", "0.0.0.0", "--port", "8000"]
