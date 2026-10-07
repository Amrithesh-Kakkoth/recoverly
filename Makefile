.PHONY: up down test seed
up:
	docker compose up --build
down:
	docker compose down
test:
	cd backend && pytest
seed:
	cd backend && python -m scripts.seed
