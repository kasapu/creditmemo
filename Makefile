.PHONY: help venv install install-azure run seed dev clean docker-build docker-run

PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8001

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

$(BIN)/activate:
	$(PY) -m venv $(VENV)

venv: $(BIN)/activate  ## Create the virtualenv

install: venv  ## Install core (offline/mock) dependencies
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt

install-azure: install  ## Install Azure deps + Playwright browser
	$(BIN)/pip install -r requirements-azure.txt
	$(BIN)/python -m playwright install chromium

run: install  ## Run the server (http://127.0.0.1:$(PORT))
	$(BIN)/python run.py

dev: install  ## Run with auto-reload
	DEBUG=true $(BIN)/uvicorn credit_memo.app:app --reload --host 127.0.0.1 --port $(PORT)

seed: install  ## Seed a sample AAPL dataset (offline demo)
	PYTHONPATH=. $(BIN)/python scripts/seed_sample.py

clean:  ## Remove venv, caches and local data
	rm -rf $(VENV) data **/__pycache__ .pytest_cache

docker-build:  ## Build the Docker image
	docker build -t credit-memo .

docker-run:  ## Run the Docker image (http://127.0.0.1:$(PORT))
	docker run --rm -p $(PORT):8001 --env-file .env credit-memo
