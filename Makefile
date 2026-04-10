# Podletters developer commands.
#
# Usage: `make <target>`. Most targets wrap docker compose; `test`, `lint`
# and `format` run inside the worker image so the toolchain matches CI.

COMPOSE ?= docker compose
WORKER  ?= podletters-worker

.PHONY: help up down restart logs ps build worker-shell test lint format clean smoke-ingest smoke-llm bootstrap-voices

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Start the full stack in the background
	$(COMPOSE) up -d

down: ## Stop and remove containers (keeps volumes)
	$(COMPOSE) down

restart: ## Restart the worker and api services
	$(COMPOSE) restart worker api

logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=200

ps: ## Show service status
	$(COMPOSE) ps

build: ## Rebuild worker and api images
	$(COMPOSE) build worker api

worker-shell: ## Open an interactive shell inside the worker container
	$(COMPOSE) exec worker bash

test: ## Run pytest inside the worker container
	$(COMPOSE) exec worker pytest -q

lint: ## Run ruff lint inside the worker container
	$(COMPOSE) exec worker ruff check src tests

format: ## Run ruff format inside the worker container
	$(COMPOSE) exec worker ruff format src tests

clean: ## Remove containers AND named volumes (destructive)
	$(COMPOSE) down -v

smoke-ingest: ## Fetch + clean the first unread newsletter via the worker
	$(COMPOSE) exec worker python -m podletters.ingestion.smoke

smoke-llm: ## Generate a transcript from a sample newsletter via Ollama
	$(COMPOSE) exec worker python -m podletters.llm.smoke

bootstrap-voices: ## Generate reference WAV clips for F5-TTS via Piper
	$(COMPOSE) exec worker bash /app/scripts/bootstrap_voices.sh /app/refs
