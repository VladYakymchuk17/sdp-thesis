.PHONY: up down build logs db-shell ml-shell test lint clean

# Start all services
up:
	docker compose up -d

# Stop all services
down:
	docker compose down

# Rebuild and start
build:
	docker compose up -d --build

# View logs
logs:
	docker compose logs -f

# PostgreSQL shell
db-shell:
	docker compose exec postgres psql -U sdp -d sdp_thesis

# ML service shell
ml-shell:
	docker compose exec ml-service bash

# Run tests
test:
	cd services/ml-service && python -m pytest tests/ -v

# Lint
lint:
	cd services/ml-service && ruff check app/ tests/

# Format
format:
	cd services/ml-service && ruff format app/ tests/

# Start only PostgreSQL (for local Python dev without Docker)
db:
	docker compose up -d postgres

# Clean everything (volumes included)
clean:
	docker compose down -v
