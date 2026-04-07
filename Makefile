# Factory — coordinator config sync, agent management, and coordinator lifecycle
#
# Private config (agent-config.yaml) is gitignored and synced via rsync.
# All other changes sync via: git push whitebox main

WHITEBOX       := whitebox
FACTORY_REMOTE := /Users/nesbitt/dev/factory
CONFIG_LOCAL   := agents/ig88/config
CONFIG_REMOTE  := $(FACTORY_REMOTE)/agents/ig88/config

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Config sync (private — gitignored, rsync only)
# ---------------------------------------------------------------------------

.PHONY: sync-config
sync-config:  ## Sync agent-config.yaml to Whitebox (private, not in git)
	rsync -av $(CONFIG_LOCAL)/ $(WHITEBOX):$(CONFIG_REMOTE)/

.PHONY: sync
sync:  ## Sync source (git push) + private config (rsync) to Whitebox
	git push whitebox main
	$(MAKE) sync-config

# ---------------------------------------------------------------------------
# Coordinator lifecycle
# ---------------------------------------------------------------------------

.PHONY: reload
reload:  ## SIGHUP coordinator — reloads config without restart
	ssh $(WHITEBOX) 'kill -HUP $$(pgrep coordinator-rs)'

.PHONY: restart
restart:  ## Hard restart coordinator via launchd
	ssh $(WHITEBOX) 'launchctl kickstart -k gui/$$(id -u)/com.bootindustries.coordinator-rs'

.PHONY: deploy
deploy: sync restart  ## Sync config + restart coordinator

.PHONY: logs
logs:  ## Tail coordinator logs on Whitebox
	ssh $(WHITEBOX) 'tail -f ~/Library/Logs/factory/coordinator.log'

.PHONY: status
status:  ## Check coordinator launchd state and last 5 log lines
	@ssh $(WHITEBOX) 'launchctl list | grep coordinator-rs; echo "---"; tail -5 ~/Library/Logs/factory/coordinator.log'

# ---------------------------------------------------------------------------
# Agent provisioning
# ---------------------------------------------------------------------------

.PHONY: agent-add
agent-add:  ## Provision a new agent: NAME= PORT= MODEL= MATRIX_USER= required
	@test -n "$(NAME)"        || (echo "ERROR: NAME required";        exit 1)
	@test -n "$(PORT)"        || (echo "ERROR: PORT required";        exit 1)
	@test -n "$(MODEL)"       || (echo "ERROR: MODEL required";       exit 1)
	@test -n "$(MATRIX_USER)" || (echo "ERROR: MATRIX_USER required"; exit 1)
	bash scripts/agent-add.sh \
	    --name "$(NAME)" --port "$(PORT)" \
	    --model "$(MODEL)" --matrix-user "$(MATRIX_USER)" \
	    --prefix "$(PREFIX)" --description "$(DESCRIPTION)"

.PHONY: agent-remove
agent-remove:  ## Remove an agent — prints manual checklist
	@test -n "$(NAME)" || (echo "ERROR: NAME required"; exit 1)
	@echo "Manual removal checklist for $(NAME):"
	@echo "  1. Remove '$(NAME):' block from agents/ig88/config/agent-config.yaml"
	@echo "  2. make sync-config && make reload"
	@echo "  3. ssh whitebox 'rm -rf ~/.hermes/profiles/$(NAME)'"
	@echo "  4. Archive agents/$(NAME)/ — do not delete"
	@echo "  5. infra/ports.csv — status back to reserved"
	@echo "  6. Disable MLX-LM launchd plist on Whitebox"
	@echo "  7. Remove from scripts/matrix-cross-sign/utils/constants.ts"

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
