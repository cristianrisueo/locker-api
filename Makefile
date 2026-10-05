# Comandos del proyecto locker. Escribe "make" para ver la lista.
.PHONY: help up stop down destroy psql migrate migration rollback run check test test-unit test-integration coverage

help:  ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

# --- Base de datos (Docker) ---

up:  ## Levanta Postgres en segundo plano
	docker compose up -d

stop:  ## Apaga el contenedor sin borrarlo
	docker compose stop

down:  ## Elimina el contenedor (los datos se conservan en el volumen)
	docker compose down

destroy:  ## Elimina el contenedor Y LOS DATOS
	docker compose down -v

psql:  ## Abre una consola SQL dentro de la base de datos
	docker compose exec db psql -U locker -d locker

# --- Migraciones ---

migrate:  ## Aplica las migraciones pendientes
	uv run alembic upgrade head

migration:  ## Genera una migración desde los modelos. Uso: make migration m="mensaje"
	@test -n "$(m)" || (echo 'Falta el mensaje: make migration m="crear buildings"' && exit 1)
	uv run alembic revision --autogenerate -m "$(m)"

rollback:  ## Deshace la última migración
	uv run alembic downgrade -1

# --- Desarrollo ---

run:  ## Arranca la API con recarga automática
	uv run uvicorn locker.main:app --reload

check:  ## Formatea, pasa el linter y comprueba los tipos
	uv run ruff format . && uv run ruff check . && uv run mypy src tests

# --- Tests ---

test:  ## Unitarios + integración (necesita Docker, no el sistema desplegado)
	uv run pytest

test-unit:  ## Solo unitarios (sin Docker)
	uv run pytest tests/unit

test-integration:  ## Solo integración (Postgres efímero con testcontainers)
	uv run pytest tests/integration

coverage:  ## Unitarios + integración con informe de cobertura (terminal y htmlcov/index.html)
	uv run pytest --cov --cov-report=term --cov-report=html
