# Factory Portal — React build, local preview, and Blackbox deploy

BLACKBOX    := blackbox
REMOTE      := /home/nesbitt/projects/factory-portal
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
deploy: sync install  ## Build, sync, and install the Blackbox services

.PHONY: build
build:  ## Build the React multi-page portal into dist/
	$(PNPM) build

.PHONY: sync
sync: build sync-dist sync-runtime sync-gsd sync-repos ssh-normalize ssh-generate-index  ## Sync build output, runtime helpers, repo docs, and live task data to Blackbox

.PHONY: sync-dist
sync-dist:  ## Rsync dist/ to Blackbox
	ssh $(BLACKBOX) 'mkdir -p $(REMOTE_DIST)'
	rsync -avz --delete $(DIST)/ $(BLACKBOX):$(REMOTE_DIST)/

.PHONY: sync-runtime
sync-runtime:  ## Sync local runtime helpers needed by serve.sh and the index generator
	ssh $(BLACKBOX) 'mkdir -p $(REMOTE)/src'
	rsync -avz Makefile serve.sh server.py $(BLACKBOX):$(REMOTE)/
	rsync -avz src/generate_index.py src/normalize_fonts.py $(BLACKBOX):$(REMOTE)/src/
	ssh $(BLACKBOX) 'chmod +x $(REMOTE)/serve.sh $(REMOTE)/server.py'

.PHONY: sync-gsd
sync-gsd:  ## Seed live tasks.json + status/ into the task/status sidecar data root
	rsync -avz $(LOCAL_DEV)/factory/tasks.json $(BLACKBOX):$(REMOTE)/tasks.json
	rsync -avz $(LOCAL_DEV)/get-shit-done/status/ $(BLACKBOX):$(REMOTE)/status/

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
	  $(LOCAL_DEV)/ $(BLACKBOX):$(REMOTE)/repos/

.PHONY: ssh-normalize
ssh-normalize:  ## Normalize repo-corpus font paths on Blackbox
	ssh $(BLACKBOX) 'cd $(REMOTE) && python3 src/normalize_fonts.py --repos-dir repos/ --verbose'

.PHONY: ssh-generate-index
ssh-generate-index:  ## Rebuild dist/index.json from the synced repo corpus
	ssh $(BLACKBOX) 'cd $(REMOTE) && mkdir -p dist && python3 src/generate_index.py --repos-dir repos/ --output dist/index.json'

.PHONY: install
install: sync-runtime  ## Install or refresh the Blackbox systemd services
	ssh $(BLACKBOX) 'cd $(REMOTE) && ./serve.sh --systemd'

# ---------------------------------------------------------------------------
# Service management (Blackbox)
# ---------------------------------------------------------------------------

.PHONY: logs
logs:  ## Follow Caddy service logs on Blackbox
	ssh $(BLACKBOX) 'sudo journalctl -u factory-portal.service -f'

.PHONY: logs-gsd
logs-gsd:  ## Follow the task/status sidecar logs on Blackbox
	ssh $(BLACKBOX) 'sudo journalctl -u gsd-backend.service -f'

.PHONY: status
status:  ## Show both systemd units on Blackbox
	@ssh $(BLACKBOX) 'sudo systemctl status factory-portal.service --no-pager; echo "---"; sudo systemctl status gsd-backend.service --no-pager'

.PHONY: restart
restart:  ## Restart the Blackbox Caddy and task/status sidecar services
	ssh $(BLACKBOX) 'sudo systemctl restart gsd-backend.service && sudo systemctl restart factory-portal.service'

.PHONY: uninstall
uninstall:  ## Stop, disable, and remove the Blackbox services
	ssh $(BLACKBOX) 'sudo systemctl stop factory-portal.service gsd-backend.service; sudo systemctl disable factory-portal.service gsd-backend.service; sudo rm -f /etc/systemd/system/factory-portal.service /etc/systemd/system/gsd-backend.service; sudo systemctl daemon-reload'
	@echo "ok Removed factory-portal.service + gsd-backend.service"

.PHONY: verify
verify:  ## Smoke-test the live portal via Tailnet
	@echo "Testing live server..."
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41910/ > /dev/null' && echo "ok / (portal.html) OK"
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41910/pages/dashboard-v4.html > /dev/null' && echo "ok dashboard-v4.html OK"
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41910/index.json | python3 -m json.tool > /dev/null' && echo "ok index.json OK"
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41910/tasks.json | python3 -m json.tool > /dev/null' && echo "ok tasks.json OK"
	@echo "Done."

# ---------------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------------

.PHONY: dev
dev: build dev-sync-gsd dev-sync-repos dev-normalize dev-generate-index dev-server  ## Build dist/, sync local data, and preview via Caddy

.PHONY: dev-sync-gsd
dev-sync-gsd:  ## Copy current tasks.json + status/ into the local sidecar data root
	rsync -avz $(LOCAL_DEV)/factory/tasks.json ./tasks.json
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
