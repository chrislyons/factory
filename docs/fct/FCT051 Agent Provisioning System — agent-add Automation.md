# FCT051 Agent Provisioning System — agent-add Automation

**Date:** 2026-04-07
**Status:** Implemented
**Scope:** `scripts/agent-add.sh`, `scripts/agent-add-config.py`, `Makefile`

---

## Summary

Modular provisioning system that automates end-to-end agent creation in the factory system. Replaces the manual multi-step process used for Boot, Kelk, and IG-88 with a single `make agent-add` command.

## Usage

```bash
make agent-add NAME=xamm PORT=41964 MODEL=/Users/nesbitt/models/Nanbeige4.1-3B-8bit MATRIX_USER="@xamm:matrix.org"
```

**Required parameters:**

| Param | Description |
|-------|-------------|
| `NAME` | Agent name (lowercase) |
| `PORT` | MLX-LM inference port (from `infra/ports.csv`) |
| `MODEL` | Full model path on Whitebox |
| `MATRIX_USER` | Matrix user ID (e.g., `@xamm:matrix.org`) |

**Optional parameters:**

| Param | Default | Description |
|-------|---------|-------------|
| `PREFIX` | First 3 chars uppercased | Documentation prefix |
| `DESCRIPTION` | `{Name} agent` | Agent description |

## What It Automates (7 steps)

1. **Validate** — SSH to Whitebox, duplicate check in agent-config.yaml, port lookup in ports.csv, ruamel.yaml dependency
2. **Local directory** — `agents/<name>/` with CLAUDE.md, .gitignore, .claudeignore, docs/PREFIX/, src/, tests/
3. **constants.ts** — Appends to BOT_USERS and BOT_AGENT_NAMES in `scripts/matrix-cross-sign/utils/constants.ts`
4. **agent-config.yaml** — Calls `agent-add-config.py` (ruamel.yaml, preserves inline comments)
5. **Hermes profile** — Writes `~/.hermes/profiles/<name>/config.yaml` on Whitebox via SSH heredoc (includes smart_model_routing)
6. **Sync + reload** — `make sync-config && make reload`
7. **Checklist** — Prints remaining manual steps

## What Remains Manual

- Matrix account creation (CAPTCHA/email on matrix.org)
- Pantalaimon initial login (one interactive Element session)
- Access token → BWS + plist UUID
- E2EE cross-signing (`bot-trust.ts setup-bot` + `trust-users`)
- Writing soul.md, principles.md, agents.md
- MLX-LM launchd plist + model download on Whitebox
- Matrix room creation + room entry in agent-config.yaml

## Removal

```bash
make agent-remove NAME=xamm
```

Prints a manual checklist (7 steps). No destructive automation.

## Files

| File | Role |
|------|------|
| `scripts/agent-add.sh` | Orchestrator shell script (bash 3.2 compatible) |
| `scripts/agent-add-config.py` | YAML editor using ruamel.yaml |
| `Makefile` | `agent-add` and `agent-remove` targets |
| `scripts/matrix-cross-sign/utils/constants.ts` | BOT_USERS array (appended at provision time) |

## Design Decisions

- **ruamel.yaml over PyYAML** — Preserves inline comments in agent-config.yaml (critical for the port assignment comment block)
- **SSH pre-validation** — Aborts before any writes if Whitebox is unreachable
- **Bash 3.2 compatible** — No `${var,,}` syntax; uses `tr` for case conversion (macOS ships bash 3.2)
- **Hermes smart_model_routing enabled by default** — Routes simple turns to LFM 1.2B on :41963
- **No soul.md generation** — Identity files are human-written and gitignored
- **Boot as template** — New agents get Boot's structure (work sandbox, L2 trust, Hermes runtime)

## Port Assignment

Per WHB008: ports identify agent slots (stable), models are mutable within slots. New agents should use reserved slots in the 41960-41989 range (see `infra/ports.csv`).

---

**Tags:** #provisioning #automation #agent-lifecycle
