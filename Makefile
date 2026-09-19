SHELL := /bin/sh

VENV := venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(VENV_BIN)/python
PIP := $(VENV_PYTHON) -m pip
RUFF := $(VENV_BIN)/ruff

DOCKER := docker

STACK := dev-course-811372a
COMPOSE_FILE := docker-compose.yml

TEST_DIRS := $(wildcard */test)

.DEFAULT_GOAL := help

.PHONY: help
.PHONY: install lint fix test check clean
.PHONY: build build-cloud build-gateway build-lock run restart stop status ps logs
.PHONY: check-docker check-swarm swarm-init

#========== Development ==========#

venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		python3 -m venv $(VENV); \
	else \
		echo "Virtual environment already exists."; \
	fi

install: venv
	$(PIP) install --upgrade -r requirements.txt
	$(PIP) install --editable ./lib

lint: venv
	$(VENV_PYTHON) -m pylint cloud gateway lock lib/src/lib
	$(VENV_BIN)/ruff check

fix: venv
	$(RUFF) check --fix
	$(RUFF) format

test: venv
	$(VENV_PYTHON) -m pytest $(TEST_DIRS)

check: lint test

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	rm -rf ./.pytest_cache
	rm -rf ./.ruff_cache

#========== Docker ==========#

build:
	$(DOCKER) compose -f $(COMPOSE_FILE) build

build-cloud:
	$(DOCKER) compose -f $(COMPOSE_FILE) build cloud

build-gateway:
	$(DOCKER) compose -f $(COMPOSE_FILE) build gateway

build-lock:
	$(DOCKER) compose -f $(COMPOSE_FILE) build lock

run: check-swarm
	@echo "Deploying stack '$(STACK)'..."
	$(DOCKER) stack deploy \
		--compose-file $(COMPOSE_FILE) \
		$(STACK)
	@echo
	@echo "Stack deployed."
	@$(MAKE) status

restart: stop run

stop: check-docker
	$(DOCKER) stack rm $(STACK)

status: check-docker
	$(DOCKER) stack services $(STACK)

ps: check-docker
	$(DOCKER) stack ps $(STACK)

logs: check-docker
	$(DOCKER) service logs -f $(STACK)_gateway

#========== Docker Swarm ==========#

check-docker:
	@command -v $(DOCKER) >/dev/null 2>&1 || { \
		echo "ERROR: Docker is not installed."; \
		exit 1; \
	}
	@$(DOCKER) info >/dev/null 2>&1 || { \
		echo "ERROR: Docker daemon is not running or is inaccessible."; \
		exit 1; \
	}

check-swarm: check-docker
	@state=$$($(DOCKER) info --format '{{.Swarm.LocalNodeState}}'); \
	if [ "$$state" != "active" ]; then \
		echo "ERROR: Docker Swarm is not active."; \
		echo "Run 'make swarm-init' first."; \
		exit 1; \
	fi
	@manager=$$($(DOCKER) info --format '{{.Swarm.ControlAvailable}}'); \
	if [ "$$manager" != "true" ]; then \
		echo "ERROR: This Docker node is not a Swarm manager."; \
		exit 1; \
	fi
	@nodes=$$($(DOCKER) node ls --format '{{.ID}}' 2>/dev/null | wc -l | tr -d ' '); \
	if [ "$$nodes" != "1" ]; then \
		echo "ERROR: This project supports only a single-node Swarm."; \
		echo "Found $$nodes Swarm nodes."; \
		exit 1; \
	fi

swarm-init: check-docker
	@state=$$($(DOCKER) info --format '{{.Swarm.LocalNodeState}}'); \
	if [ "$$state" = "active" ]; then \
		echo "Docker Swarm is already initialized."; \
	else \
		echo "Initializing single-node Docker Swarm..."; \
		$(DOCKER) swarm init; \
	fi


help:
	@echo "Available targets:"
	@echo "  venv         Create the Python virtual environment"
	@echo "  install      Install Python dependencies"
	@echo "  lint         Run linters"
	@echo "  fix          Automatically fix lint/format issues"
	@echo "  test         Run tests"
	@echo "  check        Run linting and tests"
	@echo "  clean        Remove generated Python files"
	@echo "  build          Build Docker images (COMPONENT=name for one)"
	@echo "  build-cloud    Build the cloud image"
	@echo "  build-gateway  Build the gateway image"
	@echo "  build-lock     Build the lock image"
	@echo "  run          Deploy the Docker Swarm stack"
	@echo "  restart      Restart the stack"
	@echo "  stop         Remove the stack"
	@echo "  status       Show stack services"
	@echo "  ps           Show stack tasks"
	@echo "  logs         Follow gateway logs"
	@echo "  swarm-init   Initialize Docker Swarm"