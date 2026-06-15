.PHONY: help install dev run worker migrate revision seed lint fmt test docker-up docker-down docker-logs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install runtime + dev deps with uv
	uv venv
	uv pip install -e ".[dev]"

run: ## Run the API locally (reload)
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run the Celery worker locally
	uv run celery -A app.workers.celery_app:celery worker --loglevel=info

migrate: ## Apply DB migrations
	uv run alembic upgrade head

revision: ## Autogenerate a migration (msg="...")
	uv run alembic revision --autogenerate -m "$(msg)"

seed: ## Seed roles/users/decoders/config/alerts
	uv run python -m app.seed

lint: ## Lint with ruff
	uv run ruff check app migrations

fmt: ## Auto-fix lint + format
	uv run ruff check --fix app migrations
	uv run ruff format app migrations

test: ## Run tests
	uv run pytest -q

docker-up: ## Build & start the full stack
	docker compose up -d --build

docker-down: ## Stop the stack
	docker compose down

docker-logs: ## Tail logs
	docker compose logs -f api worker

tls-selfsigned: ## Generate a self-signed TLS cert (HOST=, OUT= to override)
	bash deploy/gen-selfsigned-cert.sh "$(HOST)" "$(OUT)"
