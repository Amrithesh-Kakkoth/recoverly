.PHONY: up down test test-pg seed
up:
	docker compose up --build
down:
	docker compose down
test:
	cd backend && .venv/bin/pytest
# same suite on local Postgres (needs the recoverly_test database)
test-pg:
	cd backend && TEST_DATABASE_URL=postgresql+asyncpg://recoverly:recoverly@localhost:5432/recoverly_test .venv/bin/pytest
seed:
	cd backend && python -m scripts.seed
