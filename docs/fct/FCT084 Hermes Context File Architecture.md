# FCT084 Hermes Context File Architecture

**Date:** 2026-04-29
**Status:** Active
**Scope:** All Hermes profiles (Boot, Kelk, IG-88, Gonzo)

---

## Overview

Hermes Agent assembles the system prompt from multiple layered files. Understanding
the loading order, char limits, and write permissions is critical for managing agent
behavior across sessions.

## System Prompt Assembly Order

```
1. SOUL.md          — agent identity (always loaded, 20K max)
2. USER.md          — user profile snapshot (1,375 char limit)
3. MEMORY.md        — agent's personal notes snapshot (2,200 char limit)
4. Skills guidance  — skill selection instructions
5. Context files    — AGENTS.md from working directory (20K max)
6. Timestamp        — current date/time
7. Platform hints   — formatting rules per platform (Matrix, CLI, etc.)
```

## File Locations

All files are profile-scoped. Each profile has its own copy:

```
~/.hermes/profiles/<name>/
  SOUL.md                    — agent identity
  memories/
    MEMORY.md                — agent's personal notes
    USER.md                  — user profile
  skills/
    <category>/<skill>.md    — procedural knowledge
```

Root-level fallback:
```
~/.hermes/
  SOUL.md                    — default if profile SOUL.md missing
```

## File Details

### SOUL.md — Agent Identity

| Property | Value |
|----------|-------|
| Path | `~/.hermes/profiles/<name>/SOUL.md` |
| Char limit | 20,000 (hardcoded truncation) |
| Auto-written by Hermes | **NEVER** |
| Read at | Session start, injected as slot #1 |
| Fallback | `DEFAULT_AGENT_IDENTITY` (generic Hermes text) |

**Write model:** Manual only. Hermes reads SOUL.md but never writes to it.
This is the safest place for permanent behavioral rules, identity constraints,
and communication style directives.

**Content belongs here:**
- Who the agent is (name, role, personality)
- Communication style (concise, decisive, etc.)
- Behavioral constraints (what to avoid)
- Scope boundaries (what to work on, what to ignore)
- Agent-to-agent interaction rules

### USER.md — User Profile

| Property | Value |
|----------|-------|
| Path | `~/.hermes/profiles/<name>/memories/USER.md` |
| Char limit | 1,375 |
| Auto-written by Hermes | Via `memory` tool only |
| Read at | Session start (frozen snapshot) |
| Delimiter | `§` between entries |
| Config flag | `memory.user_profile_enabled: true\|false` |

**Write model:** Three paths:
1. Agent calls `memory(action="add/replace/remove", target="user")` during conversation
2. Flush mechanism (auxiliary LLM decides what to save after 6+ turns)
3. Manual edit on disk between sessions

**Content belongs here:**
- User name, role, timezone
- Communication preferences
- Tool/platform preferences (pnpm over npm, paid over free)
- Pet peeves and workflow habits
- How the user likes information presented

**Content does NOT belong here:**
- Agent identity (→ SOUL.md)
- Project details (→ AGENTS.md or FCT docs)
- Infrastructure facts (→ MEMORY.md)

### MEMORY.md — Agent's Personal Notes

| Property | Value |
|----------|-------|
| Path | `~/.hermes/profiles/<name>/memories/MEMORY.md` |
| Char limit | 2,200 |
| Auto-written by Hermes | Via `memory` tool only |
| Read at | Session start (frozen snapshot) |
| Delimiter | `§` between entries |
| Config flag | `memory.memory_enabled: true\|false` |

**Write model:** Same three paths as USER.md.

**Content belongs here:**
- Environment facts (OS, machine, SSH details)
- Tool quirks and gotchas (write_file behavior, launchctl reload vs kickstart)
- Infrastructure conventions (plist rules, port assignments)
- Active project pointers (one-liners with repo paths)
- Lessons learned that prevent repeated mistakes

**Content does NOT belong here:**
- Agent identity (→ SOUL.md)
- User characteristics (→ USER.md)
- Project-specific build details (→ FCT docs or AGENTS.md)
- Task progress or session outcomes (→ session_search)
- Procedures and workflows (→ skills)

## Write Control Summary

| File | Hermes auto-writes? | Manual edit? | Flush adds entries? |
|------|---------------------|--------------|---------------------|
| SOUL.md | **Never** | Yes (safe) | No |
| USER.md | Via memory tool only | Yes (keep § format) | Yes (append) |
| MEMORY.md | Via memory tool only | Yes (keep § format) | Yes (append) |
| AGENTS.md | Never | Yes | No |

## Flush Mechanism

After every `flush_min_turns` user turns (default: 6), or before context
compression, Hermes runs a "memory flush":

1. Makes ONE API call to the auxiliary LLM
2. Only the `memory` tool is available (no terminal, no file, etc.)
3. The LLM reviews the conversation and decides what to save
4. Uses `memory(action="add")` — append only, never overwrites existing entries
5. Flush artifacts are stripped from the message list after completion

The flush prompt instructs: "Save anything worth remembering — prioritize user
preferences, environment details, tool quirks, and stable conventions."

**Risk:** The auxiliary LLM may add low-quality or redundant entries that bloat
the limited char budget. Periodic manual cleanup is recommended.

## Frozen Snapshot Behavior

Both MEMORY.md and USER.md are loaded from disk ONCE at session start and
frozen into `_system_prompt_snapshot`. Mid-session writes (via memory tool or
flush) update the file on disk but do NOT update the current session's system
prompt. Changes take effect at the NEXT session start.

This means:
- Memory writes during a session don't affect the current conversation
- Manual edits between sessions are picked up immediately
- Multiple concurrent sessions read the same snapshot they started with

## Source Code References

| File | Key functions |
|------|--------------|
| `agent/prompt_builder.py` | `load_soul_md()` (line 932), `build_context_files_prompt()` (line 1045) |
| `run_agent.py` | System prompt assembly (line 4060), `flush_memories()` (line 7336) |
| `tools/memory_tool.py` | `MemoryStore` class (line 105), `add/replace/remove/save_to_disk` |
| `hermes_constants.py` | `get_hermes_home()` (line 11) |

## Config Settings

```yaml
memory:
  memory_enabled: true          # Enable/disable MEMORY.md injection
  user_profile_enabled: true    # Enable/disable USER.md injection
  memory_char_limit: 2200       # Max chars for MEMORY.md content
  user_char_limit: 1375         # Max chars for USER.md content
  flush_min_turns: 6            # Min user turns before auto-flush
  provider: ''                  # External memory provider (hindsight, mem0, etc.)
```

Note: `user_profile_enabled` was `false` in Boot's config as of 2026-04-29.
This means USER.md was NOT being injected into Boot's system prompt.

## Reorganization Plan

See FCT085 (pending) for the proposed content migration strategy.
