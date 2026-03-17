# Factory Portal — Consolidated HTML Docs Server
# Makefile: deploy, sync, dev, service management
#
# Quickstart:
#   make dev                   Full local pipeline: sync → serve
#   make deploy                Full remote deploy: sync + install systemd
#   make sync                  rsync pages + fonts + repos + shared to Blackbox
#   make status                Show systemd service status on Blackbox
#   make logs                  Follow service logs on Blackbox
#   make retire-old            Stop + disable old explainers + gsd-dashboard services

BLACKBOX    := blackbox
REMOTE      := /home/nesbitt/projects/factory-portal
LOCAL_DEV   := /Users/chrislyons/dev
SRC_FONTS   := $(LOCAL_DEV)/shared-fonts/input
STAGE       := /tmp/factory-portal-stage
SHELL       := /bin/bash

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Remote deploy
# ---------------------------------------------------------------------------

.PHONY: deploy
deploy: sync install  ## Full remote deploy: sync + install systemd

.PHONY: sync
sync: sync-pages sync-fonts sync-shared sync-src sync-gsd sync-repos ssh-normalize ssh-generate-index  ## rsync all portal files to Blackbox

.PHONY: sync-pages
sync-pages:  ## Copy HTML/CSS/JS pages from source repos, fix font paths, rsync to Blackbox
	@echo "Staging pages..."
	@rm -rf $(STAGE)/pages && mkdir -p $(STAGE)/pages
	# Dashboard v4
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v4.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v1.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v2.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v4.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v4-runtime.js $(STAGE)/pages/
	# Explainers v4
	cp $(LOCAL_DEV)/codex-frontend/explainers/index-v4.html $(STAGE)/pages/explainers-v4.html
	cp $(LOCAL_DEV)/codex-frontend/explainers/explainers-v4.css $(STAGE)/pages/
	# Topology (self-contained)
	cp $(LOCAL_DEV)/factory/wireframes/topology.html $(STAGE)/pages/
	# Architecture gallery
	cp $(LOCAL_DEV)/factory/wireframes/architecture-gallery.html $(STAGE)/pages/
	# Standalone guides
	cp $(LOCAL_DEV)/explainers/standalone/credential-rotation-guide.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/explainers/standalone/local-inference-guide.html $(STAGE)/pages/
	# Repo commands
	cp $(LOCAL_DEV)/blackbox/docs/repo-commands.html $(STAGE)/pages/
	# --- Font path fixes (on copies, not source files) ---
	# Architecture gallery, credential-rotation, repo-commands: shared-fonts → ../fonts/
	cd $(STAGE)/pages && sed -i '' "s|url('[^']*shared-fonts/input/[^']*/\(Input[^']*\.ttf\)')|url('../fonts/\1')|g" \
		architecture-gallery.html credential-rotation-guide.html repo-commands.html 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' 's|url("[^"]*shared-fonts/input/[^"]*/\(Input[^"]*\.ttf\)")|url("../fonts/\1")|g' \
		architecture-gallery.html credential-rotation-guide.html repo-commands.html 2>/dev/null || true
	# Explainers v4 CSS: absolute /fonts/ → relative ../fonts/
	cd $(STAGE)/pages && sed -i '' "s|url('/fonts/|url('../fonts/|g" explainers-v4.css 2>/dev/null || true
	# Dashboard v2 CSS: check and fix font paths
	cd $(STAGE)/pages && sed -i '' "s|url('/fonts/|url('../fonts/|g" dashboard-v2.css 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' "s|url('[^']*shared-fonts/input/[^']*/\(Input[^']*\.ttf\)')|url('../fonts/\1')|g" dashboard-v2.css 2>/dev/null || true
	# Explainers v4 HTML: fix references to index page
	cd $(STAGE)/pages && sed -i '' 's|href="/"|href="../"|g' explainers-v4.html 2>/dev/null || true
	# Dashboard v4 runtime: fix relative fetch paths (./tasks.json → /tasks.json, ./status/ → /status/)
	# Pages are served from /pages/ but tasks.json and status/ live at document root
	cd $(STAGE)/pages && sed -i '' "s|fetch('./tasks.json'|fetch('/tasks.json'|g" dashboard-v4-runtime.js
	cd $(STAGE)/pages && sed -i '' "s|fetch(\`./status/|fetch(\`/status/|g" dashboard-v4-runtime.js
	@echo "ok Pages staged with font path + runtime fetch fixes"
	# Sync to Blackbox
	ssh $(BLACKBOX) 'mkdir -p $(REMOTE)/pages'
	rsync -avz $(STAGE)/pages/ $(BLACKBOX):$(REMOTE)/pages/

.PHONY: sync-fonts
sync-fonts:  ## rsync Input fonts to Blackbox fonts/
	ssh $(BLACKBOX) 'mkdir -p $(REMOTE)/fonts'
	rsync -avz \
	  $(SRC_FONTS)/InputSans/InputSans/InputSans-Regular.ttf \
	  $(SRC_FONTS)/InputSans/InputSans/InputSans-Medium.ttf \
	  $(SRC_FONTS)/InputSans/InputSans/InputSans-Bold.ttf \
	  $(SRC_FONTS)/InputSans/InputSans/InputSans-Light.ttf \
	  $(SRC_FONTS)/InputMono/InputMono/InputMono-Regular.ttf \
	  $(BLACKBOX):$(REMOTE)/fonts/

.PHONY: sync-shared
sync-shared:  ## rsync shared CSS/JS to Blackbox shared/
	ssh $(BLACKBOX) 'mkdir -p $(REMOTE)/shared'
	rsync -avz ./shared/ $(BLACKBOX):$(REMOTE)/shared/

.PHONY: sync-gsd
sync-gsd:  ## rsync tasks.json + status/ from get-shit-done to Blackbox
	rsync -avz $(LOCAL_DEV)/get-shit-done/tasks.json $(BLACKBOX):$(REMOTE)/tasks.json
	rsync -avz $(LOCAL_DEV)/get-shit-done/status/ $(BLACKBOX):$(REMOTE)/status/

.PHONY: sync-repos
sync-repos:  ## rsync HTML corpus to Blackbox repos/ (for explainers-v4)
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

.PHONY: sync-src
sync-src:  ## rsync src/, serve.sh, Makefile, portal.html, server.py to Blackbox
	rsync -avz src shared serve.sh Makefile portal.html $(BLACKBOX):$(REMOTE)/
	rsync -avz $(LOCAL_DEV)/get-shit-done/server.py $(BLACKBOX):$(REMOTE)/server.py
	ssh $(BLACKBOX) 'chmod +x $(REMOTE)/serve.sh'

.PHONY: ssh-normalize
ssh-normalize:  ## Run normalize_fonts.py on Blackbox after sync
	ssh $(BLACKBOX) 'cd $(REMOTE) && python3 src/normalize_fonts.py --repos-dir repos/ --verbose'

.PHONY: ssh-generate-index
ssh-generate-index:  ## Run generate_index.py on Blackbox after sync
	ssh $(BLACKBOX) 'cd $(REMOTE) && python3 src/generate_index.py --repos-dir repos/ --output index.json'

.PHONY: install
install: sync-src  ## Install systemd services on Blackbox
	ssh $(BLACKBOX) 'cd $(REMOTE) && ./serve.sh --systemd'

# ---------------------------------------------------------------------------
# Service management (Blackbox)
# ---------------------------------------------------------------------------

.PHONY: logs
logs:  ## Follow Caddy service logs on Blackbox
	ssh $(BLACKBOX) 'sudo journalctl -u factory-portal.service -f'

.PHONY: logs-gsd
logs-gsd:  ## Follow GSD backend logs on Blackbox
	ssh $(BLACKBOX) 'sudo journalctl -u gsd-backend.service -f'

.PHONY: status
status:  ## Show both service statuses on Blackbox
	@ssh $(BLACKBOX) 'sudo systemctl status factory-portal.service --no-pager; echo "---"; sudo systemctl status gsd-backend.service --no-pager'

.PHONY: restart
restart:  ## Restart both services on Blackbox
	ssh $(BLACKBOX) 'sudo systemctl restart gsd-backend.service && sudo systemctl restart factory-portal.service'

.PHONY: retire-old
retire-old:  ## Stop + disable old explainers.service and gsd-dashboard.service
	@echo "Retiring old services..."
	-ssh $(BLACKBOX) 'sudo systemctl stop explainers.service 2>/dev/null; sudo systemctl disable explainers.service 2>/dev/null'
	-ssh $(BLACKBOX) 'sudo systemctl stop gsd-dashboard.service 2>/dev/null; sudo systemctl disable gsd-dashboard.service 2>/dev/null'
	@echo "ok Old services retired (explainers + gsd-dashboard)"

.PHONY: uninstall
uninstall:  ## Stop + disable + remove factory-portal services on Blackbox
	ssh $(BLACKBOX) 'sudo systemctl stop factory-portal.service gsd-backend.service; sudo systemctl disable factory-portal.service gsd-backend.service; sudo rm -f /etc/systemd/system/factory-portal.service /etc/systemd/system/gsd-backend.service; sudo systemctl daemon-reload'
	@echo "ok Removed factory-portal.service + gsd-backend.service"

.PHONY: verify
verify:  ## Smoke-test the live portal via Tailnet
	@echo "Testing live server..."
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41933/ > /dev/null' && echo "ok / (portal.html) OK"
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41933/pages/dashboard-v4.html > /dev/null' && echo "ok dashboard-v4.html OK"
	@ssh $(BLACKBOX) 'curl -sf -u admin:$$PORTAL_PASSWORD http://100.87.53.109:41933/index.json | python3 -m json.tool > /dev/null' && echo "ok index.json OK"
	@echo "Done."

# ---------------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------------

.PHONY: dev
dev: dev-sync dev-server  ## Full local dev pipeline: sync + serve

.PHONY: dev-sync
dev-sync: dev-sync-pages dev-sync-fonts dev-sync-shared  ## Local sync pipeline

.PHONY: dev-sync-pages
dev-sync-pages:  ## Stage pages locally
	@rm -rf $(STAGE)/pages && mkdir -p $(STAGE)/pages
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v4.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v1.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v2.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v4.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/dashboard/dashboard-v4-runtime.js $(STAGE)/pages/
	cp $(LOCAL_DEV)/codex-frontend/explainers/index-v4.html $(STAGE)/pages/explainers-v4.html
	cp $(LOCAL_DEV)/codex-frontend/explainers/explainers-v4.css $(STAGE)/pages/
	cp $(LOCAL_DEV)/factory/wireframes/topology.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/factory/wireframes/architecture-gallery.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/explainers/standalone/credential-rotation-guide.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/explainers/standalone/local-inference-guide.html $(STAGE)/pages/
	cp $(LOCAL_DEV)/blackbox/docs/repo-commands.html $(STAGE)/pages/
	# Font path fixes (same as remote sync-pages)
	cd $(STAGE)/pages && sed -i '' "s|url('[^']*shared-fonts/input/[^']*/\(Input[^']*\.ttf\)')|url('../fonts/\1')|g" \
		architecture-gallery.html credential-rotation-guide.html repo-commands.html 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' 's|url("[^"]*shared-fonts/input/[^"]*/\(Input[^"]*\.ttf\)")|url("../fonts/\1")|g' \
		architecture-gallery.html credential-rotation-guide.html repo-commands.html 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' "s|url('/fonts/|url('../fonts/|g" explainers-v4.css 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' "s|url('/fonts/|url('../fonts/|g" dashboard-v2.css 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' "s|url('[^']*shared-fonts/input/[^']*/\(Input[^']*\.ttf\)')|url('../fonts/\1')|g" dashboard-v2.css 2>/dev/null || true
	cd $(STAGE)/pages && sed -i '' 's|href="/"|href="../"|g' explainers-v4.html 2>/dev/null || true
	# Dashboard v4 runtime: fix relative fetch paths (same as remote sync-pages)
	cd $(STAGE)/pages && sed -i '' "s|fetch('./tasks.json'|fetch('/tasks.json'|g" dashboard-v4-runtime.js
	cd $(STAGE)/pages && sed -i '' "s|fetch(\`./status/|fetch(\`/status/|g" dashboard-v4-runtime.js
	@mkdir -p pages
	rsync -avz $(STAGE)/pages/ ./pages/
	@echo "ok Pages staged locally"

.PHONY: dev-sync-fonts
dev-sync-fonts:  ## Copy Input fonts to local ./fonts/
	@mkdir -p fonts
	cp $(SRC_FONTS)/InputSans/InputSans/InputSans-Regular.ttf fonts/
	cp $(SRC_FONTS)/InputSans/InputSans/InputSans-Medium.ttf fonts/
	cp $(SRC_FONTS)/InputSans/InputSans/InputSans-Bold.ttf fonts/
	cp $(SRC_FONTS)/InputSans/InputSans/InputSans-Light.ttf fonts/
	cp $(SRC_FONTS)/InputMono/InputMono/InputMono-Regular.ttf fonts/
	@echo "ok Fonts copied to ./fonts/"

.PHONY: dev-sync-shared
dev-sync-shared:  ## shared/ is served directly from ./shared/ (no copy needed)
	@echo "ok shared/ served directly"

.PHONY: dev-sync-repos
dev-sync-repos:  ## rsync HTML corpus to local ./repos/
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
dev-generate-index:  ## Generate ./index.json from ./repos/
	python3 src/generate_index.py --repos-dir ./repos/ --output ./index.json

.PHONY: dev-server
dev-server:  ## Start Caddy locally with --open
	./serve.sh --open

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' | sort
