.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.PHONY: build
build:  ## Build the application
	docker compose -f dev.docker-compose.yaml build

.PHONY: up
up: ## Start the application as a background process
	docker compose -f dev.docker-compose.yaml up -d

.PHONY: down
down: ## Stop the application
	docker compose -f dev.docker-compose.yaml down

.PHONY: logs
logs: ## View the logs
	docker compose -f dev.docker-compose.yaml logs -f

.PHONY: migrate
migrate: ## Run migrations
	docker compose -f dev.docker-compose.yaml exec attendee-app-local python manage.py migrate

.PHONY: lint
lint: ## Run the ruff linter.
	ruff check --fix
	ruff format
