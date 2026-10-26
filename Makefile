.PHONY: help ingest test up down restart scale logs clean

help:
	@echo "Available commands:"
	@echo "  make ingest     - Ingest tariff corpus and build FAISS indices"
	@echo "  make test       - Run pytest test suite"
	@echo "  make up         - Build and start all services via Docker Compose"
	@echo "  make down       - Stop and remove all Docker Compose containers"
	@echo "  make restart    - Restart all Docker Compose containers"
	@echo "  make scale      - Scale worker service to 3 instances"
	@echo "  make logs       - Tail Docker Compose logs"
	@echo "  make clean      - Clean cache and temporary files"

ingest:
	python -m ingestion.ingest

test:
	pytest tests/ -v

up:
	docker compose up --build -d

down:
	docker compose down

restart:
	docker compose down && docker compose up --build -d

scale:
	docker compose up --scale worker=3 -d

logs:
	docker compose logs -f

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache
