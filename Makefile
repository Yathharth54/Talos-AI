# Developer commands (spec 03 §5). Aliases only.
.PHONY: up down db migrate web fake test test-int fe

TEST_COMPOSE = docker compose -p talos-test -f compose.yml -f compose.test.yml

up:
	docker compose up --build

down:
	docker compose down

db:
	docker compose -f compose.yml -f compose.dev.yml up -d db

migrate:
	uv run alembic upgrade head

web:
	uv run talos-web

fake:
	TALOS_FAKE_GRAPH=1 uv run talos-web

test:
	uv run pytest

test-int:
	$(TEST_COMPOSE) run --rm --build tests || ($(TEST_COMPOSE) down -v; exit 1)
	$(TEST_COMPOSE) down -v

fe:
	cd frontend && npm run dev
