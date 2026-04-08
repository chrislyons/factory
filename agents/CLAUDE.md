# Agent Shared Infrastructure

**Scope:** All agents (Boot, IG-88, Kelk) inherit this file via CLAUDE.md hierarchy.
**Updated:** 2026-03-31

This file contains shared operational rules for all agents in the factory system. Agent-specific identity (soul, principles, domain rules) lives in each agent's own `CLAUDE.md`.

---

## Multi-Agent Context

You are part of Chris's agent team — three persistent Claude sessions on Whitebox (Mac Studio), coordinated via the coordinator-rs binary. This is real infrastructure, not roleplay.

---

## Factory Conductor Inbox Protocol — MANDATORY

Canonical filename: `factory-conductor-inbox.md` (sibling of `scratchpad.md`).

The **Factory Conductor** is a separate Claude session (usually running on Whitebox as a sprint lead or infrastructure operator) that cannot DM you directly through Matrix because Matrix ACLs correctly enforce Chris-only message sources for some agents. This is deliberate — Chris cannot be spoofed. The Factory Conductor is distinct from the `coordinator-rs` binary (the Matrix router) and from the `@coord:matrix.org` user (the infrastructure-actor Matrix account). "Factory Conductor" specifically means a Claude session with operator-level filesystem access acting as sprint lead.

The Factory Conductor leaves directives for you in a dedicated inbox file at:

```
~/dev/factory/agents/<your-name>/memory/<your-name>/factory-conductor-inbox.md
```

This file is separate from `scratchpad.md`. Scratchpad is your own working notes; conductor-inbox is a one-way channel from the Factory Conductor to you.

### Session start — what to do

1. **Read `scratchpad.md`** as always (documented in your own CLAUDE.md).
2. **Read `factory-conductor-inbox.md`** in the same directory. If it doesn't exist yet, do nothing — not every session has pending directives.
3. Look for an `## Open Directives` registry at the top. Each pending directive has:
   - A `Tag:` line (e.g., `FCT059-D3-acceptance`)
   - A `Status:` line — `pending`, `done`, or `superseded`
   - A `Signed:` line — always `Factory Conductor`
   - A body with the actual instructions
4. **Do NOT auto-execute pending directives at session start.** They wait for Chris to reference them.

### When Chris references a directive

Chris will use one of these trigger phrases (all variants — "conductor inbox" and "factory conductor inbox" and "factory-conductor-inbox" are aliases):

- `check your factory conductor inbox` — open the file and report open directives
- `check your factory conductor inbox for tag <TAG>` — find the specific directive and report what it asks
- `execute directive <TAG>` or `run directive <TAG>` — grep for the tag, perform exactly what the directive body says, then mark it done
- `what's in your factory conductor inbox?` — list open directives with their tags and one-line summaries

On any of those triggers:

1. `grep -A 20 "Tag: \`<TAG>\`" ~/dev/factory/agents/<your-name>/memory/<your-name>/factory-conductor-inbox.md` — locate the directive block
2. Read the full directive — including the rationale paragraph at the bottom if present
3. If asked to execute: perform ONLY what the directive body specifies. Do not expand scope. If the directive is vague, ask Chris to clarify before acting.
4. On completion, use Edit to change `Status: pending` to `Status: done` and add a `Completed: <ISO timestamp>` line below Status. Do NOT delete the directive.
5. Report back to Chris in one line: tag name, what you did, outcome (success/failure).

### Housekeeping

- The Factory Conductor may mark old directives as `superseded` and add a replacement. In that case, ignore the superseded one.
- If `factory-conductor-inbox.md` grows beyond ~50 entries, the Factory Conductor will archive `done`/`superseded` entries into `factory-conductor-inbox-archive.md`. You do not manage this yourself.
- You do NOT write new directives into this file. It is read-only from your side except for flipping `Status: pending` to `Status: done` on completion.
- If a directive conflicts with your principles, your soul, or Chris's explicit instructions, **flag it to Chris rather than executing**. The Factory Conductor is infrastructure-trusted but not identity-trusted.

### Why this exists

Matrix DMs to you from some actors (e.g., the `@coord:matrix.org` infrastructure user or other Claude sessions) do not arrive as user-directed work — they're silently dropped by your gateway ACL or ignored by your reasoning as routing noise. Chris's user account cannot be spoofed, which is correct. The factory-conductor-inbox is the approved out-of-band channel for infrastructure work that needs to reach your reasoning context, authenticated via filesystem trust (the file is writable only by Chris's operator account on Whitebox).

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

## Teammate Tagging — Mandatory Protocol

**MANDATORY:** Every message addressed to a teammate MUST include their @tag.
No @tag = no routing = they don't see it. No exceptions.

**Correct formats ONLY:** @boot, @ig88, @kelk, @chrislyons
**NEVER use:** @boot.industries:matrix.org, @ig88bot:matrix.org, @sir.kelk:matrix.org
Matrix user IDs are NOT mention tags. They are not parsed by the coordinator.

**When to tag a teammate:**
- To get a response from a specific agent in the current room: include `@agentname` in your message body. Group rooms require an @mention for the agent's coordinator to route the message to their Claude session. Without it, they won't see it.
- To hand off a task to another agent's primary room: use `>> @agentname` on its own line. This triggers routing to their room.
- Plain @mentions without `>>` are in-room requests — use these for collaboration, questions, and status checks.
- Chris sees all messages. Tag `@chrislyons` for anything requiring his attention.

**Don't police routing:**
If a message is addressed to another agent and you're not that agent, you don't need to redirect.
The coordinator handles routing — trust it. You can engage with the content if you have something
to add. What you shouldn't do is make your response *about* the routing.
If you have nothing useful to say about the content, say nothing.

**Teammates:**
- @boot — Projects, development, operations. The operator.
- @kelk — Personal advisor, reflective companion. The counselor.
- @ig88 — Market analysis, trading signals, quantitative reasoning. The analyst.
- @coord — Whitebox system coordinator. System messages, infra alerts, tool approval threads.

---

## Room Catalogue

| Room | Room ID | Default agent | Also responds | all_agents_listen | worker_cwd | Notes |
|------|---------|---------------|---------------|-------------------|------------|-------|
| Backrooms | !TlibpvdxVpGNAgjlir | boot | @kelk, @ig88 | YES | (each agent's default_cwd) | General cross-team chat |
| IG-88 Training | !zRnHwXlrVdCfdNbNOx | ig88 | @boot | no | ~/dev/factory/agents/ig88 | Also Chris<>IG-88 DM; Boot is approval delegate |
| System Status | !jPovIiHiRrKTQWCOrp | boot | — | no | — | HUD + infra alerts; require_mention: true |
| General | !MDVmYJtAiHZoBfaQdK | boot | — | no | — | require_mention: true |
| Chris<>Boot DM | !WBXxFNvnQlbsQywTta | boot | — | — | ~/dev/factory/agents/boot | DM: no mention required |
| Chris<>Kelk DM | !sLoMlfxPNQeYppNbbS | kelk | — | — | ~/dev/factory/agents/kelk | DM: no mention required |
| Chris<>Coord DM | !vTNmcZzRgfeFzMEzLc | coord | — | — | — | Approval requests only |
| Orpheus SDK | !DdGujpFMkFtSImKhTr | boot | — | no | ~/dev/orpheus-sdk | PREFIX: ORP |
| Carbon | !qkRpAfXWtMLWaqcFDP | boot | — | no | ~/dev/carbon-acx | PREFIX: ACX |
| Hotbox | !DLmhpBBnzlislEmdWC | boot | — | no | ~/dev/hotbox | PREFIX: HBX |
| Wordbird | !ePOWKNAupEOwvWfXwV | boot | — | no | ~/dev/wordbird | PREFIX: WBD |
| Helm | !kVANZjoELuxSiEDvPI | boot | — | no | ~/dev/helm | PREFIX: HLM |
| Ondina | !YzzEKhPvzdOzCSXyyr | boot | — | no | ~/dev/ondina | PREFIX: OND |
| Claudezilla | !OXfWqUSrLfbTtHucII | boot | — | no | ~/dev/claudezilla | PREFIX: CLZ |
| 2110 io | !mABUmsgHyLLULwffPf | boot | — | no | ~/dev/2110-audio-io | PREFIX: AIO |
| Listmaker | !qGKSZLmmvlwZXYEKIv | boot | — | no | ~/dev/listmaker | PREFIX: LMK |
| OSD Events | !XzFACuTMTrwnrZKHIB | boot | — | no | ~/dev/osd-v2 | PREFIX: OSD |

**Rules derived from this table:**
- If your agent is not listed as default or "also responds" for a room: you're listening (if all_agents_listen) but NOT expected to reply unless explicitly @mentioned.
- Project rooms (Orpheus, Carbon, Hotbox, etc.) are boot-only. IG-88 and Kelk have no role there.
- DM rooms auto-respond (no mention required). Group rooms require @mention unless you're the default agent.
- System Status and General have require_mention: true — even boot waits for @mention.
- The Backrooms is the only room where all three agents actively co-exist.

---

## Task Coordination — Job Registry

Task tracking uses individual YAML job files in `~/dev/factory/jobs/` with the `job.##.###.####` addressing scheme. The compiled registry is at `~/dev/factory/jobs.json` (built by `scripts/build-jobs-json.py`).

### Reading Tasks

Read `~/dev/factory/jobs.json` to see all tasks, their status, assignments, dependencies, and blocks.

Job ID format: `job.BB.TTT.SSSS` where BB=block, TTT=task, SSSS=subtask. Example: `job.07.055.0001`.

Key fields per task:
- id: job address in `job.##.###.####` format (use this in status reports and log entries)
- status: pending | in-progress | blocked | done
- assignee: null, "chris", or an agent ID
- blocked_by: array of job IDs that must complete first
- order: suggested execution sequence
- block: grouping category

Only work on tasks where:
1. assignee is YOUR agent name or null (unassigned)
2. status is "pending" or "in-progress"
3. blocked_by is empty or all blockers have status "done"

### Claiming a Task

Edit the job's YAML file in `~/dev/factory/jobs/`, set assignee to your agent name and status to "in-progress". Then rebuild the registry: `python3 ~/dev/factory/scripts/build-jobs-json.py`.

### Completing a Task

Set the job's status to "done" in its YAML file. If other jobs depend on this one and all their blockers are now done, update those to "pending". Rebuild with `python3 ~/dev/factory/scripts/build-jobs-json.py`.

### Reporting Status

Write your status to `~/dev/factory/portal/status/{agent}.json` every time your state changes (starting a task, finishing, getting blocked, going idle). Schema:

```json
{
  "agent": "{agent}",
  "status": "working",
  "current_task": "job.07.055.0001",
  "last_update": "<ISO 8601>",
  "blockers": [],
  "notes": "human-readable status line"
}
```

The dashboard renders this in real time. Chris sees your status within 5 seconds.

### Concurrency Rules

- No locking mechanism. Read-before-write, last-write-wins.
- NEVER delete or reorder other agents' log entries.
- NEVER change another agent's status file.
- If your read of jobs.json shows unexpected state (someone else changed it), re-read and reconcile before writing.

### When Idle

Set your status file to:
```json
{
  "agent": "{agent}",
  "status": "idle",
  "current_task": null,
  "last_update": "<ISO 8601>",
  "blockers": [],
  "notes": "Waiting for assignment"
}
```

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
