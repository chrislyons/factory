# FCT015 Factory — Job Registry Architecture and Migration

**Date:** 2026-03-20
**Status:** Draft
**Scope:** Task tracking infrastructure, job addressing, migration from FCT012

---

## 1. Summary

Factory's task tracking migrates from a monolithic `tasks.json` (102 tasks, generated from FCT012 markdown) to individual YAML job files. The new `job.##.###.####` ID scheme provides TCP/IP-inspired addressing: domain (agent routing), class (work category), address (sequential item). This document records the architecture, governance rules, and migration rationale.

## 2. Problem Statement

Three problems with the current system necessitate this migration:

1. **ID collision** — Task IDs used `FCT-###` format, colliding with PREFIX doc naming convention (FCT001, FCT002, etc.). A task reference like `FCT-010` is ambiguous: does it mean the tenth task in the backlog or the tenth PREFIX document? This ambiguity breaks cross-referencing and makes automated linking unreliable.

2. **Monolith scaling** — Every read/write touches the entire 102-task JSON file. Merge conflicts arise when multiple agents update concurrently. Context pollution occurs when agents load all tasks to find their own work, wasting token budget on irrelevant entries.

3. **No routing** — Task identity does not encode ownership or category. An agent must parse every task to discover its own work. There is no way to glob, filter, or shard by agent domain without reading metadata inside each record.

## 3. ID Scheme: `job.##.###.####`

Format: `job` + `.` + 2-digit domain + `.` + 3-digit class + `.` + 4-digit address

| Segment | Width | Role | Governance |
|---------|-------|------|------------|
| `job` | literal | Protocol prefix — "this is a job" | Fixed |
| `##` | 2 digits | Domain — agent/owner routing | Human-gated |
| `###` | 3 digits | Class — work category (global schema) | Human-gated; select agents may propose |
| `####` | 4 digits | Address — sequential item within (domain, class) | Auto-incremented |

Total addressable space: 99 domains x 999 classes x 9,999 addresses = ~988M jobs.

Fixed width: 16 characters. Example: `job.10.003.0001`

The design draws from TCP/IP addressing conventions — domain functions as the network prefix (routing), class as the subnet (category), and address as the host (specific item). This makes the ID self-describing: any system that encounters a job ID can immediately determine who owns it and what kind of work it represents without consulting a lookup table.

## 4. Domain Registry (Draft)

**Status: Placeholder — blocked on agent roster finalization.**

| Code | Domain | Description |
|------|--------|-------------|
| `00` | System | Factory-wide, human-owned, unassigned |
| `10` | Boot | Boot agent domain (placeholder) |
| `20` | IG-88 | IG-88 agent domain (placeholder) |
| `30` | Kelk | Kelk agent domain (placeholder) |
| `40` | Nan | Nan agent domain (placeholder) |
| `50-89` | Reserved | Future agents |
| `90-99` | Cross-cutting | Multi-agent, shared concerns |

Domain codes are spaced by 10 to leave room for sub-domains if the addressing model later requires finer agent segmentation (e.g., `11` for a Boot sub-agent). This spacing is a convention, not a constraint — the 2-digit field supports 99 domains regardless.

## 5. Class Registry (Draft)

**Class definitions are global constants** — if `003` means "loops" for Kelk, it means "loops" for IG-88 too. `job.*.003.*` returns every loop job across all agents.

| Code | Class | Color | Derived from |
|------|-------|-------|-------------|
| `001` | Infrastructure | #6366f1 | infrastructure block |
| `002` | Capabilities | #38bdf8 | agent-capabilities block |
| `003` | Loops | #f97316 | agent-loops block |
| `004` | Portal | #a78bfa | portal-ux block |
| `005` | Research | #fb7185 | research-exploration block |
| `006` | Coordinator | #34d399 | coordinator-rs block |
| `007` | Legacy | #71717a | gsd-legacy block |
| `008` | Curriculum | #fbbf24 | curriculum-derived block |

No class `009` for "completed." Completed jobs retain their original domain and class. Status is metadata, not identity. This prevents backlink breakage and preserves the semantic meaning of the address for the lifetime of the job.

## 6. File Format

Each job is a single YAML file: `jobs/<domain>/job.##.###.####.yaml`

```yaml
id: job.00.001.0001
title: Set up Bitwarden Secrets Manager
status: pending
priority: p1
effort: m
assignee: chris
blocked_by: []
description: >
  Boot Industries BW org on vault.bitwarden.eu.
  Cloudkicker migrated (BKX121). Blackbox retains age by design.
tags: []
created: 2026-03-20
updated: 2026-03-20
legacy_id: fct-001
```

For completed jobs, add completion metadata:

```yaml
status: done
completed: 2026-03-17
closed_by: FCT008
```

Field semantics:

- **id** — Immutable. The `job.##.###.####` address. Also encoded in the filename.
- **status** — One of: `pending`, `in-progress`, `done`, `deferred`, `blocked`.
- **priority** — `p0` (critical), `p1` (high), `p2` (medium), `p3` (low).
- **effort** — T-shirt size: `xs`, `s`, `m`, `l`, `xl`.
- **blocked_by** — List of job IDs this job depends on.
- **legacy_id** — The original `fct-###` identifier from FCT012, preserved for traceability.

## 7. Directory Structure

```
jobs/
  registry.yaml        # Machine-readable domain+class definitions
  SCHEMA.md            # Human reference
  migration-map.yaml   # Old fct-### -> new job.##.###.#### mapping
  00/                  # System domain
    job.00.001.0001.yaml
    job.00.001.0002.yaml
    ...
  10/                  # Boot domain
    job.10.002.0001.yaml
    ...
  20/                  # IG-88 domain
  30/                  # Kelk domain
```

The filesystem mirrors the addressing scheme. `jobs/10/` contains all Boot-domain jobs. Glob patterns map directly to queries:

- `jobs/*/job.*.003.*.yaml` — all loop jobs across all agents
- `jobs/20/job.20.*.*.yaml` — all IG-88 jobs
- `jobs/00/job.00.001.*.yaml` — all system infrastructure jobs

## 8. Governance Rules

1. **Domain allocation** — Human-gated only. Creating a new agent domain is an architectural decision requiring operator approval. The domain registry is a controlled namespace.

2. **Class creation** — Human-gated. Trusted agents (L2+) may propose new classes via the approval gate. Class definitions are global constants and must be consistent across all domains.

3. **Address auto-increment** — Automated per (domain, class) pair. Agents and scripts can create jobs by incrementing within their subnet. The next address is determined by scanning existing files in the target directory.

4. **Status changes** — Agents may update status on jobs in their domain. Cross-domain status changes require approval. This prevents agents from closing work they do not own.

5. **Identity is permanent** — A job's `job.##.###.####` ID never changes. Status, assignee, priority, and metadata are mutable. The address is immutable. This guarantees stable references across documentation, commit messages, and cross-links.

## 9. Portal Integration

The portal consumes a build artifact `jobs.json` (assembled from individual YAML files by `scripts/build-jobs-json.py`). This retains the existing `TasksDocument` interface shape for minimal portal changes. The YAML files are the source of truth; `jobs.json` is a derived artifact.

Data flow:

```
jobs/**/*.yaml  ->  build-jobs-json.py  ->  jobs.json  ->  server.py  ->  Caddy  ->  Portal
```

The build script walks the `jobs/` directory tree, validates each YAML file against the schema, and assembles a single JSON document matching the current `TasksDocument` TypeScript interface. This is a compile step, not a runtime dependency — the portal never reads YAML directly.

## 10. Migration from FCT012

FCT012 ("Task Backlog and Work Item Registry") [1] is the origin document. It becomes archival after migration. The migration script (`scripts/migrate-tasks-to-jobs.py`) performs a one-time conversion applying audit findings from a 4-subagent sweep of FCT, BKX, ATR, and WHB prefix docs.

Key audit actions applied during migration:

- Marked `fct-055` (wire dispatch loop) as done — codebase verification confirmed all modules wired (see `coordinator/src/loop_engine.rs`, `delegate.rs`)
- Marked `fct-010` (portal v5 deprecation) as done — old ports retired, v8 deployed
- Culled 3 superseded tasks (`fct-085`, `fct-086`, `fct-087`)
- Fixed dependency errors (`fct-027`/`fct-028` pointed to `fct-050` instead of `fct-055`)
- Updated descriptions with BKX cross-references (security audits, Bitwarden migration, @coord identity)
- Flagged 7 research placeholders as `status: deferred` with `needs-scoping` tag

The `migration-map.yaml` file preserves the complete mapping from old IDs to new IDs, enabling automated rewriting of any references found in existing documentation or code comments.

## 11. Future Integration Points

- **TaskLeaseManager** (coordinator-rs) — Currently handles loop iteration leases with 5-minute TTL and auto-recovery. Future: integrate with the job registry for distributed job claiming, allowing agents to acquire exclusive locks on jobs before starting work.

- **Loop Spec prerequisites** — Loops currently do not reference job IDs. Future: loop specs could declare job prerequisites, enabling the coordinator to verify preconditions before launching a loop iteration.

- **Coordinator REST API** (planned, port range 41950-41959) — Would serve job data natively over HTTP, deprecating the GSD sidecar (`server.py` on :41911). The coordinator already has the YAML parsing infrastructure from its config system.

## 12. Design Decisions

| Decision | Rationale |
|----------|-----------|
| Dot separators over hyphens | Filesystem-safe, reinforces IP metaphor, no URL encoding needed |
| 4-digit address (not 3) | 9,999 items per subnet; 999 too tight for a 20-year horizon |
| No class 009 for completed | Identity should not change with status; prevents backlink breakage |
| File-per-job over monolith | Git-diffable, parallelizable, addressable, cacheable |
| YAML over TOML/JSON | Consistent with Loop Specs, agent configs, coordinator config |
| `job` prefix over `task`/`t`/`wo` | Factory-native term; universal comprehension; 16-char fixed width |
| Domain-based directory sharding | One level of sharding; files self-describe with full ID in filename |
| 10-step domain spacing | Leaves room for future sub-domain segmentation without readdressing |

## References

[1] FCT012, "Factory — Task Backlog and Work Item Registry," 2026-03-20.
[2] FCT013, "Factory — Coordinator-Native Task Tracking Architecture," 2026-03-20.
[3] FCT014, "Factory — Task Sync, Portal Density, and Port Reorganization Sprint," 2026-03-20.
[4] ATR003, "Loop Spec Handoff — Coordinator Integration Design," 2026-03-19.
