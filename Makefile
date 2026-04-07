.PHONY: build gen deploy dev logs ps down clean site

OVERLAYS  ?= mariadb,redis
PROJECT   ?= synie-erpnext

## Build the custom Docker image
build:
	@bash scripts/build.sh

## Generate docker-compose.yaml from base + overlays
gen:
	@bash scripts/gen-compose.sh $(OVERLAYS)

## Deploy (or update) services
deploy:
	@bash scripts/deploy.sh

## Dev mode: generate with dev overlay, then deploy
dev:
	@bash scripts/gen-compose.sh mariadb,redis,dev
	@bash scripts/deploy.sh

## View logs
logs:
	@docker compose -p $(PROJECT) -f docker-compose.yaml logs -f

## List running services
ps:
	@docker compose -p $(PROJECT) -f docker-compose.yaml ps

## Stop all services
down:
	@docker compose -p $(PROJECT) -f docker-compose.yaml down

## Stop all services and remove volumes
clean:
	@docker compose -p $(PROJECT) -f docker-compose.yaml down -v

## Create a new site (usage: make site SITE=erp.localhost PASS=admin)
site:
	@docker compose -p $(PROJECT) -f docker-compose.yaml exec backend \
		bench new-site $(SITE) \
			--mariadb-user-host-login-scope='%' \
			--db-root-password=$(DB_PASSWORD) \
			--admin-password=$(PASS) \
			--install-app erpnext \
			--set-default
