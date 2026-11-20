SHELL := /bin/sh

PYTHON ?= python3.15
NODE ?= node
VENV := venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(VENV_BIN)/python
PIP := $(VENV_PYTHON) -m pip
RUFF := $(VENV_BIN)/ruff

DOCKER := docker
COMPOSE := $(DOCKER) compose -f docker-compose.yml
# The default stack with the cloud and the gateways on the -openssl<version>
# images (make migrate). openssl.env pins that OpenSSL; exported, docker
# compose fills it into docker-compose.migrated.yml.
COMPOSE_MIGRATED := $(COMPOSE) -f docker-compose.migrated.yml
include openssl.env
export OPENSSL_VERSION OPENSSL_SHA256

CERTS_DIR := data/certs

.DEFAULT_GOAL := help

.PHONY: help
.PHONY: install lint fix test e2e check clean certs
.PHONY: build build-cloud build-gateway build-reader run migrate restart stop ps logs
.PHONY: run-scaled stop-scaled ps-scaled logs-scaled
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

# Unit and integration tests (the testpaths in pyproject.toml), then the
# control panel's JavaScript unit tests on Node's built-in test runner.
test: venv
	$(VENV_PYTHON) -m pytest
	@command -v $(NODE) >/dev/null || { echo "Node.js is needed for the panel's JavaScript tests"; exit 1; }
	$(NODE) --test tests/unit/cloud/static/*.test.mjs

# Builds the images, then runs the compose stack from them.
e2e: venv check-docker build
	$(VENV_PYTHON) -m pytest tests/e2e

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

# Every image, and the -openssl<version> cloud and gateway images.
build:
	$(COMPOSE) build
	$(COMPOSE_MIGRATED) build cloud gateway-1

build-cloud:
	$(COMPOSE) build cloud
	$(COMPOSE_MIGRATED) build cloud

build-gateway:
	$(COMPOSE) build gateway-1
	$(COMPOSE_MIGRATED) build gateway-1

build-reader:
	$(COMPOSE) build reader-1

# Everything on the base image's OpenSSL, which has the ML-KEM vulnerability.
run: check-docker certs
	$(COMPOSE) up --build --detach
	@$(MAKE) ps

# Moves the cloud and every gateway to the -openssl<version> images (SCRUM-55):
# the scaled stack's if it is running, else the default stack's. make run (or
# make run-scaled) moves them back.
migrate: check-docker certs
	@if [ -f $(SCALED_DIR)/$(SCALED_FILE) ] && [ -n "$$($(SCALED) ps -q)" ]; then \
		compose='$(SCALED_MIGRATED)'; \
	else \
		compose='$(COMPOSE_MIGRATED)'; \
	fi; \
	set -x; \
	$$compose up --build --detach cloud $$($$compose config --services | grep '^gateway-')

restart: stop run

stop: check-docker
	$(COMPOSE) down

ps: check-docker
	$(COMPOSE) ps

logs: check-docker
	$(COMPOSE) logs -f $(SERVICE)

#========== Scaled stack ==========#
# The default stack plus GATEWAYS sites of READERS readers each, the last
# CLASSICAL of them without ML-KEM. lib.topology generates it into SCALED_DIR
# (gitignored). It uses the default stack's ports, so only one runs at a time.

GATEWAYS ?= 10
READERS ?= 8
CLASSICAL ?= 2
SCALED_DIR := data-scaled
SCALED_FILE := docker-compose.scaled.yml
SCALED := env DATA_DIR=./$(SCALED_DIR) $(DOCKER) compose -p dev-course-scaled \
	-f docker-compose.yml -f $(SCALED_DIR)/$(SCALED_FILE)
SCALED_MIGRATED := $(SCALED) -f docker-compose.migrated.yml \
	-f $(SCALED_DIR)/docker-compose.migrated.yml

run-scaled: check-docker venv
	@if [ -n "$$($(COMPOSE) ps -q)" ]; then \
		echo "ERROR: the default stack is running (same ports): make stop first."; \
		exit 1; \
	fi
	$(VENV_PYTHON) -m lib.topology $(SCALED_DIR) $(GATEWAYS) $(READERS) $(CLASSICAL)
	@$(MAKE) build
	$(SCALED) up --detach --remove-orphans
	@echo "Control panel: https://localhost:8444 (CA: $(SCALED_DIR)/certs/ca.pem)"

stop-scaled: check-docker
	@if [ -f $(SCALED_DIR)/$(SCALED_FILE) ]; then $(SCALED) down; fi

ps-scaled: check-docker
	$(SCALED) ps

logs-scaled: check-docker
	$(SCALED) logs -f $(SERVICE)

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
	@echo "  test           Run unit and integration tests, and the panel's JavaScript tests"
	@echo "  e2e            Build the images and run the end-to-end tests on them"
	@echo "  check          Run linting and tests"
	@echo "  clean          Remove generated Python files"
	@echo "  certs          Generate the dev CA and server certificates"
	@echo "  build          Build all Docker images, with the -openssl$(OPENSSL_VERSION) cloud and gateway"
	@echo "  build-cloud    Build the cloud images (plain and -openssl$(OPENSSL_VERSION))"
	@echo "  build-gateway  Build the gateway images (plain and -openssl$(OPENSSL_VERSION))"
	@echo "  build-reader   Build the reader image"
	@echo "  run            Start the system with docker compose, on the base image's OpenSSL"
	@echo "  migrate        Move the cloud and every gateway to OpenSSL $(OPENSSL_VERSION) (scaled stack if running)"
	@echo "  restart        Restart the system"
	@echo "  stop           Stop and remove the containers"
	@echo "  ps             Show container status"
	@echo "  logs           Follow logs (SERVICE=name for one service)"
	@echo "  run-scaled     Start the default stack plus GATEWAYS=10 sites of READERS=8 readers"
	@echo "  stop-scaled    Stop and remove the scaled stack"
	@echo "  ps-scaled      Show the scaled stack's container status"
	@echo "  logs-scaled    Follow the scaled stack's logs (SERVICE=name for one service)"
