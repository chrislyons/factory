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
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
