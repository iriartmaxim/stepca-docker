# stepca-docker — atajos de operación
# Uso: make <target>
.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose

ROOT_PORT ?= 9000
INTERMEDIATE_PORT ?= 9001
RA_PORT ?= 9100
UI_PORT ?= 8088

.PHONY: help secrets env up down restart reset status logs test config pull backup restore renew ui-full stats backup-pg

help: ## Muestra esta ayuda
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

env: ## Crea .env desde .env.example si no existe
	@test -f .env || cp .env.example .env && echo "✅ .env listo"

secrets: ## Genera contraseñas fuertes en secrets/
	@bash scripts/gen-secrets.sh

up: env ## Levanta el stack HA completo (Postgres+réplicas+HAProxy+obs+UI) sin pasos manuales
	@bash scripts/bootstrap.sh

down: ## Detiene el stack (conserva el estado)
	@$(COMPOSE) down

restart: ## Reinicia los servicios
	@$(COMPOSE) restart

reset: ## DESTRUYE estado (volúmenes + persistent/) y levanta de cero
	@echo "⚠️  Esto borra toda la PKI. Ctrl-C para abortar…"; sleep 4
	@$(COMPOSE) down -v --remove-orphans || true
	@rm -rf persistent/root persistent/intermediate persistent/ra persistent/tmp
	@$(MAKE) up

status: ## Estado y salud de los servicios
	@$(COMPOSE) ps

logs: ## Sigue los logs de los 3 servicios
	@$(COMPOSE) logs -f --tail=100

config: ## Valida la configuración de compose
	@$(COMPOSE) config >/dev/null && echo "✅ compose válido"

pull: ## Descarga las imágenes
	@$(COMPOSE) pull

test: ## Smoke test end-to-end (salud de las 3 CAs)
	@bash scripts/smoke-test.sh

stats: ## Abre info del balanceador (HAProxy stats en :8404)
	@echo "HAProxy stats: http://localhost:$${HAPROXY_STATS_PORT:-8404}"
	@$(COMPOSE) ps

backup: ## Backup consistente de secrets + persistent (backups/)
	@bash scripts/backup.sh

backup-pg: ## Dump de las bases PostgreSQL a backups/
	@mkdir -p backups
	@$(COMPOSE) exec -T postgres pg_dump -U $${PG_USER:-stepca} stepca_int > backups/stepca_int-$$(date +%Y%m%d-%H%M%S).sql
	@$(COMPOSE) exec -T postgres pg_dump -U $${PG_USER:-stepca} stepca_ra  > backups/stepca_ra-$$(date +%Y%m%d-%H%M%S).sql
	@echo "✅ Dumps en backups/"

restore: ## Restaura un backup: make restore FILE=backups/xxx.tar.gz
	@bash scripts/restore.sh "$(FILE)"

renew: ## Renueva la intermedia si está por vencer
	@bash scripts/renew-intermediate.sh

ui-full: ## Reconfigura la UI con control+emisión (⚠️ monta el socket de Docker)
	@echo "⚠️  Modo completo: la UI monta /var/run/docker.sock (superficie privilegiada)."
	@$(COMPOSE) -f compose.yaml -f compose.ui-full.yaml up -d --build stepca-ui
	@echo "✅ UI (control+emisión) en http://localhost:$(UI_PORT)"
