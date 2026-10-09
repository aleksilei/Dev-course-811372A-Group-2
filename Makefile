SHELL := /bin/sh

PYTHON ?= python3.13
VENV := venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(VENV_BIN)/python
PIP := $(VENV_PYTHON) -m pip
RUFF := $(VENV_BIN)/ruff

DOCKER := docker
COMPOSE := $(DOCKER) compose -f docker-compose.yml

CERTS_DIR := data/certs

.DEFAULT_GOAL := help

.PHONY: help
.PHONY: install lint fix test check clean certs
.PHONY: build build-cloud build-gateway build-reader run restart stop ps logs
.PHONY: check-docker

#========== Development ==========#

venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV); \
	else \
		echo "Virtual environment already exists."; \
	fi

install: venv
	$(PIP) install --upgrade -r requirements.txt
	$(PIP) install --editable ./lib

lint: venv
	$(VENV_PYTHON) -m pylint --recursive=y cloud gateway reader lib tests
	$(VENV_BIN)/ruff check
	$(VENV_BIN)/ruff format --check

fix: venv
	$(RUFF) check --fix
	$(RUFF) format

# Unit and integration tests: the testpaths in pyproject.toml.
test: venv
	$(VENV_PYTHON) -m pytest

check: lint test

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	rm -rf ./.pytest_cache
	rm -rf ./.ruff_cache

# gateway-2.pem is the newest certificate, so setups made before it get a new set.
certs: $(CERTS_DIR)/gateway-2.pem

$(CERTS_DIR)/gateway-2.pem:
	$(VENV_PYTHON) -m lib.certs $(CERTS_DIR)

#========== Docker ==========#

build:
	$(COMPOSE) build

build-cloud:
	$(COMPOSE) build cloud

build-gateway:
	$(COMPOSE) build gateway-1

build-reader:
	$(COMPOSE) build reader-1

run: check-docker certs
	$(COMPOSE) up --build --detach
	@$(MAKE) ps

restart: stop run

stop: check-docker
	$(COMPOSE) down

ps: check-docker
	$(COMPOSE) ps

logs: check-docker
	$(COMPOSE) logs -f $(SERVICE)

check-docker:
	@command -v $(DOCKER) >/dev/null 2>&1 || { \
		echo "ERROR: Docker is not installed."; \
		exit 1; \
	}
	@$(DOCKER) info >/dev/null 2>&1 || { \
		echo "ERROR: Docker daemon is not running or is inaccessible."; \
		exit 1; \
	}


help:
	@echo "Available targets:"
	@echo "  venv           Create the Python virtual environment (PYTHON=$(PYTHON))"
	@echo "  install        Install Python dependencies"
	@echo "  lint           Run linters"
	@echo "  fix            Automatically fix lint/format issues"
	@echo "  test           Run unit and integration tests"
	@echo "  check          Run linting and tests"
	@echo "  clean          Remove generated Python files"
	@echo "  certs          Generate the dev CA and server certificates"
	@echo "  build          Build all Docker images"
	@echo "  build-cloud    Build the cloud image"
	@echo "  build-gateway  Build the gateway image"
	@echo "  build-reader   Build the reader image"
	@echo "  run            Start the system with docker compose"
	@echo "  restart        Restart the system"
	@echo "  stop           Stop and remove the containers"
	@echo "  ps             Show container status"
	@echo "  logs           Follow logs (SERVICE=name for one service)"
