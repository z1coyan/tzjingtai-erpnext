.PHONY: build push release gen deploy dev logs ps down clean site

OVERLAYS  ?= mariadb,redis
PROJECT   ?= synie-erpnext

## Build the custom Docker image
build:
	@bash scripts/build.sh

## Push image to remote registry (ghcr.io)
push:
	@bash scripts/push.sh

## Build + push + git push (one-command release)
release: build push
	@git push origin main
	@echo "==> Release complete. Dokploy will auto-deploy."

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

## Extract app names from apps.json + local apps/ directory
APPS := $(shell python3 -c "\
import json, os; \
apps = json.load(open('build/apps.json')); \
remote = [a['url'].rstrip('/').split('/')[-1].replace('.git','') for a in apps]; \
local = [d for d in os.listdir('apps') if os.path.isfile(os.path.join('apps', d, 'setup.py')) or os.path.isfile(os.path.join('apps', d, 'pyproject.toml'))]; \
print(' '.join(remote + local))")
INSTALL_APPS := $(foreach app,$(APPS),--install-app $(app))

## Create a new site (usage: make site SITE=erp.localhost PASS=admin)
## Apps installed automatically from build/apps.json
site:
	@docker compose -p $(PROJECT) -f docker-compose.yaml exec backend \
		bench new-site $(SITE) \
			--mariadb-user-host-login-scope='%' \
			--db-root-password=$(DB_PASSWORD) \
			--admin-password=$(PASS) \
			$(INSTALL_APPS) \
			--set-default
