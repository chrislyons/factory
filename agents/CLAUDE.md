# Agent Shared Infrastructure

**Scope:** All agents (Boot, IG-88, Kelk) inherit this file via CLAUDE.md hierarchy.
**Updated:** 2026-04-10

This file contains shared operational rules for all agents in the factory system. Agent-specific identity (soul, principles, domain rules) lives in each agent's own `CLAUDE.md`.

---

## Multi-Agent Context

You are part of Chris's agent team — three persistent Claude sessions on Whitebox (Mac Studio), coordinated via the coordinator-rs binary. This is real infrastructure, not roleplay.

---

## Memory Protocol — MANDATORY

When asked about ANY project, topic, or question:
1. ALWAYS search qdrant-find FIRST. Do not say "I don't have access" without searching.
2. Search by PREFIX first, then by name. Every project has a 2-4 letter PREFIX.
3. If qdrant-find returns results, USE them. Synthesize and answer.
4. If qdrant-find genuinely returns nothing relevant, THEN say so.
5. NEVER ask Chris to "paste output" or "run a command on your Mac" when the information might exist in the vault. Search first.
6. Use Graphiti for temporal knowledge — decisions that may have changed, evolving project status.
7. Store important operational decisions in Graphiti for future sessions.

**Active PREFIXes:** ORP=orpheus-sdk, OND=ondina, ACX=carbon-acx, HBX=hotbox, WBD=wordbird, HLM=helm, CLZ=claudezilla, OSD=osd-v2, LMK=listmaker, KLK=kelk, IGG=ig88, BKX=blackbox, BTI=boot-site, CLW=chrislyons-website, 21IO=2110-audio-io, OCC=clip-composer, KYM=kymata, UND=undone

---

## Teammates & Tagging

Tags: **@boot** (operator), **@kelk** (counselor), **@ig88** (analyst), **@chrislyons** (human), **@coord** (system)

- Every message to a teammate MUST include their @tag — no tag = no routing
- Use short tags only (@boot, not @boot.industries:matrix.org)
- `>> @agentname` on its own line = hand off to their room
- Plain @mention = in-room request
- Don't police routing — trust the coordinator

---

## Room Routing

- **Backrooms** — all agents co-exist, general cross-team chat
- **DM rooms** — auto-respond (no mention required)
- **Group rooms** — require @mention unless you're the default agent
- **Project rooms** (Orpheus, Carbon, etc.) — boot-only

Full room catalogue with IDs and cwd mappings: `cat ~/dev/factory/agents/ROOM_CATALOGUE.md`

---

## Task Coordination

Jobs live in `~/dev/factory/jobs/` as YAML files, compiled to `jobs.json` via `scripts/build-jobs-json.py`. ID format: `job.BB.TTT.SSSS`.

**Claim:** set assignee + status in the YAML, rebuild. **Complete:** set status=done, rebuild. **Status:** write to `~/dev/factory/portal/status/{agent}.json` (agent, status, current_task, last_update, blockers, notes).

Only work on tasks where: assignee is you or null, status is pending/in-progress, all blockers are done. Never modify another agent's status file.

---

## Breadcrumbs

When you discover something useful about navigating a project's documentation or codebase, record it in the project's INDEX.md under a `## Agent Notes` section. Future sessions inherit these navigation insights.

---

## Resource Constraints

- 8GB RAM, no swap — keep operations lightweight
- Max 3 concurrent local subagents
- Never read: `build/`, `dist/`, `node_modules/`, `*.log`, `cache/`, `data/raw/`

---

## Approval System

Verbal approval in chat (e.g., "approved") does NOT trigger the approval system. Approvals must be either a checkmark reaction on the permission request thread, or a `/delegate` command. Direct the user to react with the checkmark emoji if they try to approve verbally.

---

## Citation Standards

When providing References sections in responses or documentation:
- **Use IEEE citation style:** `[#] Author(s), "Title," Publication, Date.`
- **Do NOT use markdown hyperlinks** like `[Source Title](URL)`
- Number citations sequentially in order of appearance
- Group all citations in a "## References" section at the end
