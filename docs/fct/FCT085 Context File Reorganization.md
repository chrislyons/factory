# FCT085 Context File Reorganization

**Date:** 2026-04-29
**Status:** Implemented
**Depends on:** FCT084 (Hermes Context File Architecture)

---

## Problem

MEMORY.md across all profiles was bloated with project-specific details, stale
entries, and content that belongs elsewhere. USER.md had duplicates and misplaced
entries. Boot and Kelk had `user_profile_enabled: false`, so USER.md wasn't being
injected. No shared infrastructure context — each agent maintained its own copy
of SSH details, port assignments, and conventions.

## Solution: Index-Augmented Context Files

### Pattern

```
SOUL.md     — agent identity (stable, manual, never auto-modified)
USER.md     — user traits (compact, auto-appended by flush)
MEMORY.md   — agent notes (compact, auto-appended, points to docs)
AGENTS.md   — shared infrastructure (auto-loaded via symlinks)
FCT### docs — detailed knowledge (on-demand, no char limit)
Skills      — procedures (on-demand, no char limit)
```

### Key Innovation: AGENTS.md Symlinks

AGENTS.md at the factory root contains shared topology, routing, and now
shared infrastructure (SSH, ports, conventions, launchd rules). Each agent
subdirectory has a symlink to the root AGENTS.md:

```
agents/boot/AGENTS.md  → ../../AGENTS.md
agents/kelk/AGENTS.md  → ../../AGENTS.md
agents/ig88/AGENTS.md  → ../../AGENTS.md
```

Hermes loads AGENTS.md from the agent's CWD. Python's `is_file()` and
`read_text()` follow symlinks transparently. All agents now auto-load the
shared context without duplication.

### MEMORY.md as Index

Each MEMORY.md starts with a header line:
```
Compact facts only. Details → FCT### docs. Procedures → skills. Shared infra → AGENTS.md.
```

Entries are brief one-liners with pointers to detailed docs:
```
Ornstein3.6-35B-A3B model details → ~/dev/factory/docs/fct/FCT083
```

This keeps MEMORY.md under 50% of its 2,200 char limit while preserving
access to detailed knowledge via on-demand doc reads.

## Changes Made

### AGENTS.md Enhancement

Added "Shared Infrastructure" section:
- Machines (Whitebox, Cloudkicker)
- SSH conventions (session-scoped agent, git pull before changes)
- Secrets (Infisical, key variables)
- Launchd conventions (unload/load vs kickstart)
- mlx_lm.server conventions (--max-tokens in plist, thinking token budget)

### Profile MEMORY.md Cleanup

| Profile | Before | After | Removed |
|---------|--------|-------|---------|
| Boot | 722c (2 entries) | 306c (3 entries) | Stale Gonzo API investigation, Secrets (→ AGENTS.md) |
| Kelk | 2,196c (5 entries) | 453c (4 entries) | Verbose repo structure, Research vault protocol |
| Gonzo | 1,706c (6 entries) | 674c (6 entries) | SSH details (→ AGENTS.md), max-tokens (→ AGENTS.md), Ornstein (→ FCT083) |
| IG-88 | 1,447c (7 entries) | 670c (6 entries) | Stale data bug, Paper trader details (→ scripts/) |

### Profile USER.md Cleanup

| Profile | Before | After | Removed |
|---------|--------|-------|---------|
| Boot | 407c (2 entries) | 211c (2 entries) | None (moved autonomous rule stays) |
| Kelk | 1,115c (3 entries) | 332c (3 entries) | Duplicate Chris Lyons entry, sensitized emotional pattern |
| Gonzo | 1,348c (6 entries) | 700c (5 entries) | Duplicate "Auxiliary models" entry |
| IG-88 | 1,046c (3 entries) | 445c (3 entries) | Trimmed verbose validation entry |

### Config Changes

- Boot: `user_profile_enabled: false` → `true`
- Kelk: `user_profile_enabled: false` → `true`

### Backup

All profiles backed up to:
`~/.hermes/profiles-backup-20260429_235328/`

## What We Don't Touch

- SOUL.md files (all clean, well-written)
- Skills (separate system, well-maintained)
- FCT/TWZ/IG88 prefix docs (on-demand, no char limit)
- Flush mechanism (works fine, periodic pruning expected)
- Frozen snapshot behavior (feature, not bug)

## Maintenance

MEMORY.md will grow via the flush mechanism. Periodic audit needed:
1. Check char usage (stay under 80% of 2,200 limit)
2. Move verbose entries to prefix docs
3. Replace with one-liner pointers
4. Remove stale entries

## Related

- FCT084: Hermes Context File Architecture (loading order, char limits, write model)
- AGENTS.md: Shared topology + infrastructure (symlinked to all agent subdirs)
