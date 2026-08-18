# NZ Lotto Powerball — Makefile
# Common development and deployment tasks.

.PHONY: help install test lint run-api run-dash docker-up docker-down migrate

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install Python dependencies
	pip install -r requirements.txt

test:  ## Run full test suite (tests/ + legacy test_lotto.py)
	pytest tests test_lotto.py

test-unit:  ## Run unit tests only
	pytest tests/unit

test-integration:  ## Run integration tests only (requires DB)
	pytest tests/integration -m integration

test-fast:  ## Run tests excluding slow ones
	pytest tests -m "not slow"

test-legacy:  ## Run legacy test_lotto.py suite
	pytest test_lotto.py -v --tb=short

lint:  ## Lint with ruff
	ruff check . --ignore=F401,E402

migrate:  ## Run database migrations
	python -m alembic upgrade head

run-api:  ## Start FastAPI server
	uvicorn api:app --host 0.0.0.0 --port 8000 --reload

run-dash:  ## Start Streamlit dashboard
	streamlit run dashboard.py --server.port 8501

docker-build:  ## Build Docker image
	docker-compose build

docker-up:  ## Start services via Docker Compose
	docker-compose up -d

docker-down:  ## Stop Docker services
	docker-compose down

docker-logs:  ## View Docker logs
	docker-compose logs -f

seed-db:  ## Fetch latest draws and populate database
	python update_draws.py

seed-admin:  ## Create initial admin user
	@[ -n "$(JWT_ADMIN_PASSWORD)" ] || (echo "Set JWT_ADMIN_PASSWORD env var"; exit 1)
	JWT_ADMIN_PASSWORD=$(JWT_ADMIN_PASSWORD) python create_admin.py

check:  ## Run full validation (DB + API)
	python data_pipeline.py --validate

clean:  ## Remove cache and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache
