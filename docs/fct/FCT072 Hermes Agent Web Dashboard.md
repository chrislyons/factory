# FCT072 Hermes Agent Web Dashboard

**Date:** 2026-04-26
**Author:** Gonzo (infrastructure)
**Status:** Live

---

## Summary

The Hermes Agent web dashboard provides a browser-based UI for managing Hermes
profiles, viewing gateway status, inspecting agent sessions, and configuring
providers — all from a local web interface.

- **Version:** hermes-agent v2026.4.23 (with `[web,pty]` extras)
- **Default port:** 9119 (configurable via `--port`)
- **Binary:** `hermes dashboard` (from uv tool install)
- **Frontend:** Vite-built SPA, served from `hermes_cli/web_dist/`

## Installation

### 1. Install hermes-agent with web extras

```bash
uv tool install 'hermes-agent[web,pty] @ git+https://github.com/NousResearch/hermes-agent.git@v2026.4.23' \
  --force \
  --with 'mautrix[encryption]' \
  --with aiosqlite \
  --with asyncpg \
  --with Markdown
```

**Critical:** Must use the git URL with `[web,pty]` extras. Installing from PyPI
or without extras does NOT include the web dashboard.

### 2. Build the frontend

```bash
cd ~/.hermes/hermes-agent/web
npm install
/opt/homebrew/bin/node node_modules/vite/bin/vite.js build
```

Use `node node_modules/vite/bin/vite.js build` directly — `npx vite build` triggers
long-lived process detection in Hermes terminal tool.

### 3. Copy frontend to installed location

```bash
cp -r ~/.hermes/hermes-agent/hermes_cli/web_dist \
  ~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/hermes_cli/web_dist
```

### 4. Run the dashboard

```bash
hermes dashboard --port 9119 --host 0.0.0.0 --no-open --insecure
```

- `--insecure` required for non-localhost binding (needed for LAN access)
- `--no-open` prevents auto-opening browser

## macOS Firewall

For LAN access, add uv python to the firewall allowlist:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add \
  ~/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12
```

## Verification

```bash
curl -s http://127.0.0.1:9119/api/status | python3 -m json.tool
# Should return version, config path, gateway status
```

## Features

- Profile management (view/edit config per Hermes profile)
- Gateway status monitoring
- Session inspection and chat history
- Provider/model configuration
- Real-time agent activity

## Pitfalls

- `pip install hermes-agent[web,pty]` does NOT work — package not on PyPI
- `uv tool install hermes-agent --with 'hermes-agent[web,pty]'` fails — must use git URL
- Reinstalling with `--force` replaces the venv, losing mautrix[encryption] and other deps
- `npx vite build` is misidentified as a long-lived process — use direct node path
- Dashboard is separate from the Factory Portal (port 41910); they serve different purposes

## Relationship to Factory Portal

| Aspect | Hermes Dashboard | Factory Portal |
|--------|-----------------|----------------|
| Purpose | Hermes agent management | Factory infrastructure overview |
| Port | 9119 | 41910 |
| Scope | Per-profile agent config | Jobs, services, memory budget |
| Built by | Nous Research (upstream) | Factory team (custom) |
| Auth | None (local only) | Cookie auth (bcrypt + HMAC) |
