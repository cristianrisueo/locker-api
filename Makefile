# Comandos del proyecto locker. Escribe "make" para ver la lista.
.PHONY: help up stop down destroy psql migrate migration rollback run worker check test test-unit test-integration coverage e2e smoke

help:  ## Muestra esta ayuda
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

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

worker:  ## Arranca el worker del outbox (se para con Ctrl-C)
	uv run python -m locker.outbox.worker

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

# --- Sistema desplegado ---

# Servicios de la aplicación que levanta y para `make e2e` (la base de datos se queda en marcha)
APP_SERVICES = api-1 api-2 worker

e2e:  ## Levanta el sistema en contenedores, migra, pasa E2E + smoke y para la aplicación
	docker compose up -d --wait db
	docker compose --profile app run --rm --build migrate
	docker compose --profile app up -d --build --wait $(APP_SERVICES)
	BASE_URLS=http://127.0.0.1:8001,http://127.0.0.1:8002 uv run pytest tests/e2e; status=$$?; \
		docker compose --profile app stop $(APP_SERVICES); exit $$status

smoke:  ## Smoke contra un sistema ya levantado. Uso: make smoke BASE_URLS=http://...,http://...
	@test -n "$(BASE_URLS)" || (echo 'Falta BASE_URLS: make smoke BASE_URLS=http://...,http://...' && exit 1)
	BASE_URLS=$(BASE_URLS) uv run pytest tests/e2e/test_smoke.py
