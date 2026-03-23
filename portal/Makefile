# Factory Portal — React build, local preview, and Whitebox deploy

WHITEBOX    := whitebox
REMOTE      := /Users/nesbitt/projects/factory-portal
REMOTE_DIST := $(REMOTE)/dist
LOCAL_DEV   := /Users/chrislyons/dev
DIST        := dist
PNPM        := pnpm
SHELL       := /bin/bash

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Remote deploy
# ---------------------------------------------------------------------------

.PHONY: deploy
deploy: sync install  ## Build, sync, and install the Whitebox services

.PHONY: build
build:  ## Build the React multi-page portal into dist/
	$(PNPM) build

.PHONY: sync
sync: build sync-dist sync-runtime sync-gsd sync-repos ssh-normalize ssh-generate-index  ## Sync build output, runtime helpers, repo docs, and live task data to Whitebox

.PHONY: sync-dist
sync-dist:  ## Rsync dist/ to Whitebox
	ssh $(WHITEBOX) 'mkdir -p $(REMOTE_DIST)'
	rsync -avz --delete $(DIST)/ $(WHITEBOX):$(REMOTE_DIST)/

.PHONY: sync-runtime
sync-runtime:  ## Sync local runtime helpers needed by serve.sh and the index generator
	ssh $(WHITEBOX) 'mkdir -p $(REMOTE)/src'
	rsync -avz Makefile serve.sh server.py $(WHITEBOX):$(REMOTE)/
	rsync -avz src/generate_index.py src/normalize_fonts.py $(WHITEBOX):$(REMOTE)/src/
	ssh $(WHITEBOX) 'chmod +x $(REMOTE)/serve.sh $(REMOTE)/server.py'

.PHONY: sync-gsd
sync-gsd:  ## Seed live jobs.json + status/ into the task/status sidecar data root
	rsync -avz $(LOCAL_DEV)/factory/jobs.json $(WHITEBOX):$(REMOTE)/jobs.json
	rsync -avz $(LOCAL_DEV)/get-shit-done/status/ $(WHITEBOX):$(REMOTE)/status/

.PHONY: sync-repos
sync-repos:  ## Sync the repo corpus used by explainers-v4 and index.json
	rsync -avz --delete --prune-empty-dirs \
	  --filter='- explainers/' \
	  --filter='- **/repos/' \
	  --filter='- .git/' \
	  --filter='- node_modules/' \
	  --filter='- .DS_Store' \
	  --filter='+ */' \
	  --filter='+ */wireframes/architecture-gallery.html' \
	  --filter='+ */wireframes/architecture-gallery-v2.html' \
	  --filter='+ */docs/repo-commands.html' \
	  --filter='+ */docs/repo-commands-v2.html' \
	  --filter='- *' \
	  $(LOCAL_DEV)/ $(WHITEBOX):$(REMOTE)/repos/

.PHONY: ssh-normalize
ssh-normalize:  ## Normalize repo-corpus font paths on Whitebox
	ssh $(WHITEBOX) 'cd $(REMOTE) && python3 src/normalize_fonts.py --repos-dir repos/ --verbose'

.PHONY: ssh-generate-index
ssh-generate-index:  ## Rebuild dist/index.json from the synced repo corpus
	ssh $(WHITEBOX) 'cd $(REMOTE) && mkdir -p dist && python3 src/generate_index.py --repos-dir repos/ --output dist/index.json'

.PHONY: install
install: sync-runtime  ## Install or refresh the Whitebox launchd services
	ssh $(WHITEBOX) 'cd $(REMOTE) && ./serve.sh --systemd'

# ---------------------------------------------------------------------------
# Service management (Whitebox)
# ---------------------------------------------------------------------------

.PHONY: logs
logs:  ## Follow Caddy service logs on Whitebox
	ssh $(WHITEBOX) 'tail -f ~/Library/Logs/factory/portal.log'

.PHONY: logs-gsd
logs-gsd:  ## Follow the task/status sidecar logs on Whitebox
	ssh $(WHITEBOX) 'tail -f ~/Library/Logs/factory/gsd.log'

.PHONY: status
status:  ## Show both launchd services on Whitebox
	@ssh $(WHITEBOX) 'launchctl print system/com.factory.portal 2>&1 | head -5; echo "---"; launchctl print system/com.factory.gsd 2>&1 | head -5'

.PHONY: restart
restart:  ## Restart the Whitebox Caddy and task/status sidecar services
	ssh $(WHITEBOX) 'launchctl kickstart -k system/com.factory.gsd && launchctl kickstart -k system/com.factory.portal'

.PHONY: uninstall
uninstall:  ## Stop, disable, and remove the Whitebox services
	ssh $(WHITEBOX) 'launchctl bootout system/com.factory.portal; launchctl bootout system/com.factory.gsd'
	@echo "ok Removed com.factory.portal + com.factory.gsd"

.PHONY: verify
verify:  ## Smoke-test the live portal via Tailnet
	@echo "Testing live server..."
	@ssh $(WHITEBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.88.222.111:41910/ > /dev/null' && echo "ok / (portal.html) OK"
	@ssh $(WHITEBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.88.222.111:41910/pages/dashboard-v4.html > /dev/null' && echo "ok dashboard-v4.html OK"
	@ssh $(WHITEBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.88.222.111:41910/index.json | python3 -m json.tool > /dev/null' && echo "ok index.json OK"
	@ssh $(WHITEBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.88.222.111:41910/jobs.json | python3 -m json.tool > /dev/null' && echo "ok jobs.json OK"
	@echo "Done."

# ---------------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------------

.PHONY: build-jobs
build-jobs:  ## Build jobs.json from the factory task registry
	python3 $(LOCAL_DEV)/factory/scripts/build-jobs-json.py -o $(LOCAL_DEV)/factory/jobs.json

.PHONY: dev
dev: build dev-sync-gsd dev-sync-repos dev-normalize dev-generate-index dev-server  ## Build dist/, sync local data, and preview via Caddy

.PHONY: dev-sync-gsd
dev-sync-gsd:  ## Copy current jobs.json + status/ into the local sidecar data root
	rsync -avz $(LOCAL_DEV)/factory/jobs.json ./jobs.json
	rsync -avz $(LOCAL_DEV)/get-shit-done/status/ ./status/

.PHONY: dev-sync-repos
dev-sync-repos:  ## Sync the local repo corpus into ./repos/
	@mkdir -p repos
	rsync -avz --delete --prune-empty-dirs \
	  --filter='- explainers/' \
	  --filter='- **/repos/' \
	  --filter='- .git/' \
	  --filter='- node_modules/' \
	  --filter='- .DS_Store' \
	  --filter='+ */' \
	  --filter='+ */wireframes/architecture-gallery.html' \
	  --filter='+ */wireframes/architecture-gallery-v2.html' \
	  --filter='+ */docs/repo-commands.html' \
	  --filter='+ */docs/repo-commands-v2.html' \
	  --filter='- *' \
	  $(LOCAL_DEV)/ ./repos/

.PHONY: dev-normalize
dev-normalize:  ## Normalize font paths in ./repos/
	python3 src/normalize_fonts.py --repos-dir ./repos/ --verbose

.PHONY: dev-generate-index
dev-generate-index:  ## Generate dist/index.json from ./repos/
	@mkdir -p $(DIST)
	python3 src/generate_index.py --repos-dir ./repos/ --output ./dist/index.json

.PHONY: dev-server
dev-server:  ## Start Caddy locally with --open
	./serve.sh --open

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
