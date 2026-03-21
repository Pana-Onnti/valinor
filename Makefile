.PHONY: dev stop test test-cov lint install clean logs shell db-shell

dev:
	docker compose up -d

stop:
	docker compose down

test:
	source venv/bin/activate && pytest tests/ -v

test-cov:
	pytest tests/ --cov=. --cov-report=html --cov-report=term-missing

lint:
	flake8 api/ shared/ --max-line-length=120

install:
	pip install -r requirements.txt

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true

logs:
	docker compose logs -f api

shell:
	docker compose exec api bash

db-shell:
	docker compose exec postgres psql -U valinor -d valinor_saas
