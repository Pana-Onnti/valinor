.PHONY: help dev stop test test-cov test-fast lint typecheck install clean logs shell db-shell

# Default target
.DEFAULT_GOAL := help

##@ Help

help: ## Show available targets with descriptions
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	     /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
	     /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

dev: ## Start all services (detached)
	docker compose up -d

stop: ## Stop all services
	docker compose down

logs: ## Tail API logs
	docker compose logs -f api

shell: ## Open a shell inside the API container
	docker compose exec api bash

db-shell: ## Open a psql shell inside the Postgres container
	docker compose exec postgres psql -U valinor -d valinor_saas

install: ## Install Python dependencies
	pip install -r requirements.txt

##@ Testing

test: ## Run full test suite with verbose output
	pytest tests/ -v

test-cov: ## Run tests with HTML + terminal coverage report
	pytest tests/ --cov=api --cov=shared --cov=core \
	    --cov-report=html --cov-report=term-missing \
	    --cov-fail-under=60

test-fast: ## Run only non-slow tests (excludes performance/integration markers)
	pytest tests/ -v -m "not slow and not performance and not integration"

##@ Code Quality

lint: ## Run flake8 on api/, shared/, core/ (excludes venv)
	flake8 api/ shared/ core/ \
	    --max-line-length=120 \
	    --extend-ignore=E501,W503 \
	    --exclude=venv,.venv,__pycache__,.git

typecheck: ## Run mypy on api/ and shared/
	mypy api/ shared/ \
	    --ignore-missing-imports \
	    --no-strict-optional \
	    --exclude venv

##@ Cleanup

clean: ## Remove __pycache__, .pytest_cache, *.pyc, coverage artefacts
	find . -type d -name __pycache__ -not -path './venv/*' -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .pytest_cache -not -path './venv/*' -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name '*.pyc' -not -path './venv/*' -delete 2>/dev/null; true
	find . -type f -name '*.pyo' -not -path './venv/*' -delete 2>/dev/null; true
	rm -rf htmlcov/ .coverage coverage.xml .mypy_cache/ 2>/dev/null; true
