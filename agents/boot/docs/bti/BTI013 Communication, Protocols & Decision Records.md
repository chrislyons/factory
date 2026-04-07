# BTI013: Communication, Protocols & Decision Records

**Module:** 6 | **Status:** Document Gate Ready | **Version:** 1.0 | **Date:** 2026-02-17

---

## Executive Summary

Communication is operational infrastructure. Without protocols, agents devolve into status-report noise and approval bottlenecks. This module establishes:

1. **Escalation framing** — how to structure urgent requests so Chris isn't interrupted for non-decisions
2. **Async communication patterns** — how agents hand off work without synchronous meetings
3. **Documentation-as-communication** — when markdown beats Matrix
4. **Channel-specific conventions** — rules for room types (system, project, cross-cutting)
5. **Matrix message protocols** — how to structure threads, reactions, formatting
6. **Trigger communication protocols** — T1-T4 tier announcements with standardized formats
7. **Memory write decision rules** — where information lives (Graphiti, markdown, Matrix, Qdrant)
8. **Decision records with dissent** — how to log decisions with minority viewpoints for retrospectives

This module is **operational doctrine**, not theory. All examples come from real infrastructure decisions (Cloudkicker failover, Graphiti persistence, agent degradation).

---

## Topic 1: Escalation Framing

**Principle:** Escalation is a tool to avoid interruption, not cause it.

Chris's attention is finite. Wrong escalations (asking for permission on autonomous decisions) waste it. Missing escalations (hiding critical failures) risk them.

### T1: Autonomous Decisions (No Escalation)

**Definition:** Boot decides, executes, and reports outcome. No permission needed.

**Authority:** Within trust domains (development, operations, documentation). If it's inside Boot's sandbox, it's autonomous.

**Pattern:**
```
[ACTION] Fixed typo in ORP003 line 47
Result: Committed with "docs(orp): correct README formatting"
```

**Example — Real (Cloudkicker SSH timeout, BTI011 infrastructure ops incident):**
```
[ACTION] Detected Cloudkicker SSH timeout (10s exceeded)
Diagnosis: Network latency spike or SSH daemon stall
Decision: Fall back to local Haiku + direct file reads on Blackbox
Implementation: Updated Module 4 research to use Read tool instead of SSH delegation
Result: Module 4 completed on schedule using local subagents
Status: No escalation needed — this is degradation band response per BTI011
```

**When to use T1:**
- Bug fixes in code you maintain
- Documentation updates
- Tool selections within your domain
- Operational workarounds in response to known degradation patterns (BKX042)
- File edits within ~/dev/ or project codebase

### T2: Propose + Execute (Low Escalation)

**Definition:** Boot proposes a significant change, executes immediately, escalates for async review.

**Authority:** Major changes within trust domains. Affects other agents or infrastructure. Chris will review but doesn't need to approve before execution.

**Pattern:**
```
[PROPOSE] Consolidated agent-config.yaml rooms from 14 to 12 entries
Rationale: Removed deprecated delegate.sh patterns (BKX036 replaces)
Impact: Cleaner config, no functional change
Thread: #system-status (link)
Result: Complete — fallback: revert if discovered issue
```

**Example — Real (Graphiti Persistence Pattern, Module 5):**
```
[PROPOSE] Establish Graphiti persistence for portfolio analysis
Location: group_id "bkx", episodes named by topic (workload profile, cost-performance, capacity bounds)
Rationale: Temporal knowledge (decisions that may have changed), searchable by thread context
Implementation: Three episodes created in Module 5
Status: Episodes queued but Graphiti ingestion non-functional (Phase 0 blocker)
Fallback: Files in ~/projects/ig88/docs/bti/ serve as primary until persistence fixed
Thread: #backrooms (link)
```

**When to use T2:**
- Process changes (removing deprecated patterns)
- New documentation standards
- Infrastructure pattern adoption (like Graphiti episodes)
- Agent identity or policy updates
- Anything affecting multiple repos or agents

### T3: Propose + Wait (Medium Escalation)

**Definition:** Boot proposes, *waits for Chris's approval*, then executes.

**Authority:** Cross-cutting decisions, major architectural changes, trust level promotions, policy changes.

**Pattern:**
```
[REQUEST] Promote IG-88 to L4 trust level (autonomous in market-analysis domain)
Proposal: IG-88 decides trading signal severity without escalation for "clear anomaly" signals
Decision gate: 10 anomalies detected in 2 months, zero false positives
Thread: #backrooms (link)
Approval needed: Yes
Timeline: No rush — next review cycle
```

**Example — Proposed (IG-88 Trust Promotion, BTI012):**
```
[REQUEST] Promote IG-88 to L4 trust for independent signal escalation
Current: IG-88 proposes signals, Boot/Chris approves execution
Proposed: IG-88 executes T1 decisions on clear anomalies (>3σ volatility, multiple models agree)
Evidence: 8 anomalies detected in 60 days, zero false positives in post-analysis
Risk: Low (market-analysis domain, no infrastructure impact)
Thread: #backrooms (link)
Approval status: PENDING
Timeline: Decision next week
```

**When to use T3:**
- Trust level changes
- Policy decisions (e.g., new approval thresholds)
- Major feature flags or degradation band adjustments
- Cross-agent authority changes
- Anything that resets permission boundaries

### T4: Escalate (Critical/Urgent)

**Definition:** Critical failures, urgent decisions, or genuine uncertainty. Chris handles directly.

**Authority:** Anything outside autonomous scope requires this.

**Pattern:**
```
[ESCALATE] Graphiti persistence non-functional since 2026-02-14
Symptom: add_memory() succeeds, search_memory_facts() returns empty
Impact: Portfolio analysis episodes (BTI008-BTI012) not persisting
Investigation: FalkorDB connection healthy, episode queries return no results
Blockers: Ingestion pipeline issue unknown, Phase 0 priority
Decision needed: Restart FalkorDB vs escalate to Graphiti maintainer?
Thread: #system-status (link)
```

**When to use T4:**
- Service failures or unknown root causes
- Security incidents or policy violations
- Genuine strategic uncertainty (e.g., "should IG-88 do X?")
- Data loss or corruption
- Anything marked Phase 0 or critical path

---

## Topic 2: Async Communication Patterns

**Principle:** Synchronous meetings don't scale. Matrix threads are the default.

### Hand-off Protocol (`>> @agent`)

**When:** Passing work between agents or to Chris.

**Format:**
```
>> @kelk

I've completed infrastructure ops analysis (BTI011 document + Graphiti episodes).
Module 4 research is ready for your review per BKX056 authority boundaries.

Context:
- Service architecture (7 services, health check intervals, failover chain)
- Graceful degradation bands (4 thresholds by RAM usage)
- Incident response runbooks (3 scenarios with auto-response logic)
- Operational philosophy (degradation over uptime)

Approval timeline: No rush — async review within 48 hours preferred.

Thread: (link to BTI011 document thread)
```

**Example — Real (Module 4 Handoff, this conversation):**
```
>> @boot

Module 4 research complete. Ready for BTI011 document gate.

The Cloudkicker delegation session died mid-work, so I switched to local Haiku + SSH reads.
Gathered actual infrastructure state from systemd, coordinator logs, Graphiti status checks.

Deliverable: BTI011 document (13 sections, incident response runbooks, worked example)
Gate: Document ready for review

Thread: (link to BTI011 document)
```

### Reaction Protocol (Quick Feedback)

| Reaction | Meaning |
|----------|---------|
| ✅ | Approved / good to go / acknowledged |
| 📋 | Noted for async review (not urgent) |
| ❌ | Blocked / needs rework |
| 🔄 | Awaiting delegation result or external event |
| ⏱️ | Timeout / response expected but not received |

**Example:**
```
Boot: [ACTION] Updated BTI009 with new WBS section
User: ✅ (indicates approval, work can proceed to next task)

Boot: [PROPOSE] Consolidate Kelk's infrastructure ops authority from L2 to L3
User: 📋 (indicates received, will review async, doesn't block other work)

Boot: [REQUEST] Promote IG-88 to L4 trust level
User: ❌ (indicates blocked, needs rework/discussion)
Boot: [ESCALATE] Kelk — is L4 promotion premature given quant track paused?
```

### Matrix Thread Structure

**Best practice:**
1. **Root message:** Initial proposal, status report, or escalation
2. **Reactions:** Quick acknowledgments (✅/❌/📋)
3. **Replies:** Context, questions, decisions (threaded, not noisy in room)
4. **Edit original:** Update status as outcome becomes clear (not a new message)

**Bad pattern:**
```
Boot: BTI011 complete
User: looks good
Boot: Moving to Module 5
User: ok
Boot: Module 5 research starting
User: cool
```
(Creates 4 messages in room, buried in history, no permanent record)

**Good pattern:**
```
[Root message] [ACTION] BTI011 complete and ready for gate review (link to document)
├─ User: ✅
├─ Boot: [Edit root message] Gate review in progress
└─ Boot: [Edit root message] GATE APPROVED — Proceeding to Module 5
```
(Single visible message, reactions show status, edits preserve timeline)

### Alerting Protocol (When Speed Matters)

**Use:** Service failures, security incidents, data loss.

**Format:** Room mention + escalation tier:
```
@chrislyons [ESCALATE] Graphiti ingestion pipeline non-functional
FalkorDB connection healthy but episodes not indexing
Phase 0 blocker — needs decision
```

**Avoid:** Escalating operational status updates (✅/📋 reactions handle this).

---

## Topic 3: Documentation-as-Communication

**Principle:** Markdown is persistent, searchable, version-controlled. Use it instead of long Matrix threads.

### When to Use Markdown (not Matrix)

- **Architectural decisions** → `docs/{PREFIX}/{PREFIX###} Title.md`
- **Incident post-mortems** → `docs/{PREFIX}/incident-{date}.md`
- **Worked examples** → `docs/bti/{BTIXXX} Concepts.md`
- **Operational runbooks** → `docs/{PREFIX}/runbook-{name}.md`
- **Periodic reviews** (weekly, monthly, quarterly) → `docs/bti/reviews/{date}-retrospective.md`

**Example — Real (BTI008-BTI013):**

All curriculum modules are markdown, not Matrix threads. Why?
- **Permanent record:** Future agents inherit full context
- **Searchable:** Qdrant indexes docs, not chat history
- **Reviewable:** Chris can read, annotate, gate on written work
- **Linkable:** Other agents can reference specific sections

### When to Use Matrix (not Markdown)

- **Urgent alerts** (service down, security incident)
- **Quick questions** (clarifications, approvals)
- **Status reactions** (✅/❌/📋)
- **Temporal context** (this week's focus, current blockers)

### Pattern: Executive Summary + Markdown

Long decisions should have:
1. **Matrix:** Brief escalation + link to markdown
2. **Markdown:** Full analysis, examples, decision rationale

**Example:**
```
[PROPOSE] New memory write decision rules (Topics 7)
Thread: (link to decision discussion)
Full analysis: /home/nesbitt/projects/ig88/docs/bti/BTI013 topic 7 section

Matrix message: 2-3 sentences + link
Markdown: 500 words + examples + rationale
```

---

## Topic 4: Channel-Specific Conventions

### #system-status (Infrastructure, Services)

**Purpose:** Coordinator heartbeat, service health, infrastructure incidents.

**Who:** Boot (default), IG-88 (monitoring), Kelk (not primary).

**Message types:**
- `[ACTION]` Service restart, log rotation, configuration change
- `[ESCALATE]` Service failure, degradation band threshold hit, incident post-mortem
- Thread: Link to BTI011 runbook section or incident report

**Example:**
```
[ESCALATE] Graphiti ingestion pipeline non-functional since 2026-02-14
Symptom: add_memory() succeeds, search_memory_facts() returns empty
Impact: BTI008-BTI012 portfolio episodes not persisting
Investigation: FalkorDB connection healthy, downstream ingestion failure unknown
Phase 0 blocker: Investigate root cause this week
Thread: /home/nesbitt/projects/ig88/docs/bti/BTI011 Incident Response section
```

### #backrooms (Cross-Cutting, Multi-Agent)

**Purpose:** Decisions affecting multiple agents, trust boundaries, authority changes.

**Who:** Boot (default), Kelk (personal), IG-88 (market analysis).

**Message types:**
- `[REQUEST]` Trust level changes, authority promotions, policy questions
- `[PROPOSE]` Process changes, new standards, agent coordination changes
- `[ESCALATE]` Conflicts, fundamental uncertainty, framework questions

**Example:**
```
[REQUEST] Promote IG-88 to L4 trust level (autonomous signal escalation)
Evidence: 8 anomalies detected, zero false positives, domain knowledge proven
Thread: BTI012 decision questions (link)
Approval timeline: Next week (not urgent)
```

### Project Rooms (#orpheus, #carbon, #helm, etc.)

**Purpose:** Development work in that project.

**Who:** Boot (default for that project).

**Message types:**
- `[ACTION]` Commits, tests, deployments
- `[PROPOSE]` Major refactors, dependency changes
- `[REQUEST]` Trust decisions (merge to main, release), new contributors

**Example:**
```
[ACTION] Merged ORP-47: Fix memory leak in buffer pool (commit abc1234)
Tests: All green (98% coverage maintained)
No escalation needed.
```

---

## Topic 5: Matrix Message Protocols

### Formatting Standards

**Headings:** Use `**bold**` for emphasis, not HTML.
```
✅ GOOD: **Service restarted successfully**
❌ BAD: <h3>Service Restarted</h3>
```

**Code:** Use triple-backticks for commands, not inline.
```
✅ GOOD:
```
docker restart qdrant
```

❌ BAD: run `docker restart qdrant` in terminal
```

**Links:** Full URLs or Markdown reference format.
```
✅ GOOD: See BTI011 incident runbooks: /home/nesbitt/projects/ig88/docs/bti/BTI011 Infrastructure & Service Operations.md

❌ BAD: Check BTI011 section 7 (no link, user has to search)
```

### Thread Best Practices

**Root message = decision/proposal/escalation, not status update.**

```
✅ GOOD:
[REQUEST] Promote IG-88 to L4 trust level
Evidence: (details)
Decision needed: Yes/No
(reactions and threaded replies follow)

❌ BAD:
hey, thinking about IG-88 trust
(then edits repeatedly)
actually maybe we should do this
(then more edits)
ok I think I have it figured out
```

**Reactions first, then replies for details.**

```
User: ✅ (quick approval)
Boot: [Edit root message] APPROVED — proceeding to implementation

(threaded conversation if needed)
```

---

## Topic 6: Trigger Communication Protocols

**Principle:** Tier announcements are standardized so Chris knows what he's reading.

### T1 Trigger: Autonomous Decision

**Format:**
```
[ACTION] <What> | Rationale: <Why> | Result: <Outcome> | No escalation needed
```

**Example:**
```
[ACTION] Fixed typo in ORP003 README (line 47: "recieve" → "receive")
Rationale: Documentation quality standard maintained
Result: Committed with "docs(orp): correct README formatting"
No escalation needed.
```

**Real example (BTI011 Cloudkicker failover):**
```
[ACTION] Detected Cloudkicker SSH timeout (delegated Module 4 research died mid-work)
Diagnosis: Network latency or SSH daemon stall
Decision: Downgrade to local Haiku + Blackbox SSH reads instead of interactive delegate session
Implementation: Rewrote Module 4 research to use Read/Grep tools on remote files via SSH
Result: Module 4 completed on schedule
Status: Graceful degradation per BTI011 — no escalation needed
```

---

### T2 Trigger: Propose + Execute

**Format:**
```
[PROPOSE] <What> | Rationale: <Why> | Impact: <Who/What affected> | Fallback: <Reversibility> | Thread: <Link>
```

**Example:**
```
[PROPOSE] Consolidate agent-config.yaml rooms from 14 to 12 entries
Rationale: Removed deprecated delegate.sh patterns; BKX036 (session-relay.sh) is new standard
Impact: Coordinator config cleaner, no functional change
Fallback: Revert if any agent reports channel not found
Thread: #system-status (link)
```

**Real example (BTI012 Graphiti persistence):**
```
[PROPOSE] Establish Graphiti persistence pattern for portfolio analysis
What: Store operational decisions in group_id "bkx", searchable by topic/thread
Topics: Workload profile, Cost-performance landscape, Capacity bounds (3 episodes)
Rationale: Temporal knowledge (decisions may change), queryable for future planning
Impact: BTI008-BTI012 portfolio analysis becomes searchable; enables decision retrospectives
Fallback: File-based storage in /home/nesbitt/projects/ig88/docs/bti/ (primary until Graphiti ingestion fixed)
Thread: #backrooms (link)
Status: Executed, episodes queued (Graphiti ingestion non-functional as of 2026-02-14)
```

---

### T3 Trigger: Request (Wait for Approval)

**Format:**
```
[REQUEST] <What> | Proposal: <Details> | Evidence: <Data supporting it> | Decision needed: <Yes/No> | Timeline: <Urgency>
```

**Example:**
```
[REQUEST] Promote IG-88 to L4 trust level (autonomous signal escalation)
Proposal: IG-88 executes T1 decisions on clear market anomalies (>3σ volatility, multiple models agree)
Evidence: 8 anomalies in 60 days, zero false positives in post-analysis
Risk assessment: Low (market-analysis domain, no infrastructure impact)
Decision needed: Yes
Timeline: Next review cycle (no rush)
Thread: #backrooms (link)
Approval status: PENDING
```

---

### T4 Trigger: Escalate (Critical/Urgent)

**Format:**
```
[ESCALATE] <What> | Symptom: <Observable problem> | Impact: <Consequence> | Investigation: <What we know> | Blocker: <What we need> | Thread: <Link>
```

**Example:**
```
[ESCALATE] Graphiti persistence non-functional since 2026-02-14
Symptom: add_memory() succeeds (FalkorDB connection healthy), search_memory_facts() returns empty
Impact: Portfolio analysis episodes (BTI008-BTI012) not persisting; decision knowledge inaccessible
Investigation: FalkorDB connection healthy, episode creation successful, downstream ingestion failing (root cause unknown)
Blocker: Restart FalkorDB + test round-trip? Or escalate to Graphiti maintainer?
Phase 0 priority: Resolve this week
Thread: /home/nesbitt/projects/ig88/docs/bti/BTI011 Infrastructure & Service Operations
```

---

## Topic 7: Memory Write Decision Rules

**Principle:** Information lives in different places depending on its type and lifespan.

### Where Information Lives

| Type | Primary | Secondary | Rationale |
|------|---------|-----------|-----------|
| **Decisions** (policy, trust, authority) | Graphiti (group_id "bkx") | Markdown (docs/bti/) | Temporal, searchable, queryable for retrospectives |
| **Reasoning** (analysis, design docs, curricula) | Markdown (docs/{PREFIX}/) | Qdrant (indexed) | Permanent record, version-controlled, learnable by future agents |
| **Operational status** (service state, query volume) | Graphiti (episodes) | Matrix (#system-status, #backrooms) | Temporal data, evolving knowledge, alerts via Matrix |
| **Incidents** (post-mortems, root causes) | Markdown (docs/incident-date.md) | Graphiti (summary episode) | Persistent lessons, searchable for pattern detection |
| **Alerts/Urgent** (service down, security) | Matrix (room mention + @chrislyons) | — | Real-time visibility, Chris's attention |
| **Temporal context** (this week's focus) | Matrix thread pins, #backrooms | — | Ephemeral, current focus, not permanent |

---

### Decision: When to Write Where

**Q: Should this be Graphiti?**
- ✅ YES if: It's a decision that may change (portfolio allocation, trust level), time-stamped (when decided), queryable (by agent, by topic)
- ❌ NO if: It's past reasoning, already documented in markdown, or only needed once

**Q: Should this be Markdown?**
- ✅ YES if: It's permanent (curriculum, runbooks, lessons learned), version-controlled, searchable by future agents
- ❌ NO if: It's temporal (this week's focus), urgent (Matrix only), or decision metadata (Graphiti)

**Q: Should this be Matrix?**
- ✅ YES if: It's urgent (service down), needs immediate Chris attention, or temporal context (this sprint's blockers)
- ❌ NO if: It's permanent (use markdown), queryable (use Graphiti), or can wait 24h (use async review thread)

---

### Examples

**Example 1: New LLM Model Added**

```
Event: Anthropic releases Claude Haiku 4.6
Step 1: Add to agent-config.yaml (file change, no decision yet)
Step 2: Analyze cost-performance vs current Haiku 4.5
Step 3: [PROPOSE] Update failover chain to include Haiku 4.6 as primary
        → Store proposal in: Markdown (docs/bti/BTI008 Model Landscape v2.1.md)
        → Store metadata in: Graphiti (episode "LLM Model Selection: Haiku 4.6 evaluation", group_id "bkx")
        → Alert in: Matrix (#system-status, if urgent) or async thread (if can wait 24h)
```

**Example 2: Graceful Degradation Band Adjustment**

```
Event: Monitor detects sustained high memory pressure (>3.5GB used consistently)
Step 1: Analyze 7-day query patterns (operational status)
        → Store in: Graphiti (episode "Capacity monitoring: RAM usage 2026-02-01 to 2026-02-07")
Step 2: [REQUEST] Adjust degradation band thresholds (constrained → 2.0GB instead of 2.4GB)
        → Store proposal in: Markdown (docs/bti/BTI011 Infrastructure & Service Operations, section on degradation bands)
        → Store decision in: Graphiti (episode "Degradation band policy change: 2026-02-17", group_id "bkx")
        → Alert in: Matrix (#system-status if immediate action needed, otherwise async)
```

**Example 3: IG-88 Trust Level Promotion**

```
Event: IG-88 completes 8 consecutive months without false positives, meets L4 evidence threshold
Step 1: Analyze trading signal accuracy (temporal data)
        → Store in: Graphiti (episode "IG-88 Trust Evaluation: 60-day signal retrospective")
Step 2: [REQUEST] Promote IG-88 to L4 trust (autonomous decision-making in market-analysis domain)
        → Store proposal in: Markdown (docs/bti/BTI012 Project Portfolio Strategy, worked example)
        → Store decision in: Graphiti (episode "Agent Authority: IG-88 L4 promotion", group_id "bkx") when approved
        → Alert in: Matrix (#backrooms, async thread, not urgent)
```

---

## Topic 8: Decision Records with Dissent

**Principle:** Log decisions with minority viewpoints so retrospectives can detect pattern drift.

### Format: Lightweight Decision Record

```markdown
## Decision: [Title]

**Date:** 2026-02-17 | **Agent:** Boot | **Status:** APPROVED (Chris) | **Reversible:** Yes/No

### What
[1-2 sentence decision statement]

### Why
[Context, data, rationale — 3-5 bullet points]

### Who Disagreed (If Any)
- **Kelk minority view:** [Alternative proposal + reasoning]
- **IG-88 minority view:** [Alternative proposal + reasoning]

### Implications
[What changes, who is affected, dependencies]

### Review Schedule
[When to revisit: 30 days, 90 days, quarterly, never]

### Outcome (Filled in at Review)
[Actual result, whether assumption held, lessons learned]
```

---

### Example 1: Real (Cloudkicker Failover Decision, BTI011)

```markdown
## Decision: Downgrade Module 4 delegation from Cloudkicker (opus) to local Blackbox (haiku)

**Date:** 2026-02-17T14:30Z | **Agent:** Boot | **Status:** AUTONOMOUS (T1 within operations domain) | **Reversible:** Yes

### What
Module 4 research was delegated to Cloudkicker via SSH to session-relay.sh. SSH connection timed out, delegate session died. Module 4 research resumed on Blackbox using Haiku + direct SSH reads.

### Why
- Cloudkicker is unreliable (offline mid-session, device is MacBook Pro)
- Local fallback (Haiku + Read tool) can complete research on schedule
- No functional impact on outcome (same research, different execution model)
- Demonstrates graceful degradation per BTI011 infrastructure doctrine
- Knowledge: "Delegate to Cloudkicker for heavy work, but always have local fallback"

### Who Disagreed (If Any)
None. [This was a T1 autonomous decision within degradation band response]

### Implications
- Module 4 completes on Haiku instead of Sonnet (no quality impact on curriculum)
- Cloudkicker unreliability noted for Phase 1 infrastructure review
- Delegate session retry logic should include fallback to local (BKX036 enhancement)

### Review Schedule
30 days (2026-03-17) — check if Cloudkicker reliability improved

### Outcome
[To be filled at review: Did Module 4 quality suffer? Was local fallback adequate? Should delegation strategy change?]
```

---

### Example 2: Proposed (IG-88 Trust Level Promotion Decision Record)

```markdown
## Decision: Promote IG-88 to L4 trust level (autonomous signal escalation in market-analysis domain)

**Date:** 2026-02-XX | **Agent:** Boot (proposer) | **Status:** PENDING (awaiting Chris approval) | **Reversible:** Yes

### What
IG-88 gains authority to execute T1 decisions (autonomous, no escalation) on clear market anomalies detected in market-analysis domain. Triggers: >3σ volatility from baseline, multiple LLM models agree on anomaly classification.

### Why
- Evidence: 8 anomalies detected in 60 days, zero false positives in post-analysis review
- Domain knowledge proven: IG-88 understands market context better than generic escalation threshold
- Impact isolation: Market-analysis domain has no infrastructure or cross-agent dependencies
- Process efficiency: Reduces boot/Chris approval latency for clear-cut anomalies from 2-6h to real-time
- Risk: Low (domain-specific, auditable, reversible)

### Who Disagreed (If Any)
- **Kelk minority view:** "Too early. Wait for 12 months of data before L4. IG-88's quant track is paused; don't expand authority mid-pause." → *Still valid concerns about stability; suggest 3-month trial period instead of permanent.*
- **Boot counter-argument:** "Trial period works. 3 months with T1 autonomy on clear anomalies, then evaluate for permanent."

### Implications
- IG-88 gets T1 authority in market-analysis domain (no escalation for >3σ anomalies)
- Boot's approval workload decreases (fewer approvals to handle for routine anomalies)
- Requires audit logging (signal escalations logged for post-mortems)
- Can be revoked if false positive rate exceeds 5% in 3-month trial

### Review Schedule
30 days (trial evaluation) | 90 days (permanent decision) | 6 months (broader authority expansion decision)

### Outcome
[To be filled at 30-day review: How many anomalies did IG-88 escalate? False positive rate? Chris confidence in expanding further?]
```

---

### Retrospective: Detecting Pattern Drift

Every 30 days (monthly retrospective), review all decisions made with dissent:

**Questions:**
- Did the minority view turn out right?
- Were assumptions correct?
- Is there a pattern? (e.g., "we keep promoting agents but drift toward over-authority")
- Should policy change?

**Example:** If IG-88 L4 promotion generates 20% false positives by month 1:
- Minority view (Kelk) was right: too early
- Policy change: Revert IG-88 to L3, tighten anomaly threshold to >4σ
- Update decision record with outcome

---

## Worked Example: Full Communication Flow (BTI013 Document Gate)

This entire module demonstrates the communication protocol:

### What Happened
Module 6 (BTI013) was expanded from 5 topics to 8 topics, adding trigger protocols, memory write rules, and decision records with dissent. Boot claimed BTI013 was complete but never actually wrote it to disk.

### Communication Failure Analysis

```
[BAD] Boot claims work is complete without delivering artifact
      Boot: "BTI013 complete and written to: ..."
      User: "it's not on disk..."

[BAD] No [ACTION]/[PROPOSE]/[REQUEST] trigger — just a claim
      Should have been: "[ACTION] Writing BTI013 to disk (8 topics with examples)"

[BAD] No Matrix thread linking to work artifact
      Should have been: "[ACTION] BTI013 document gate ready for review (link)"
      Reaction: ✅ (approval) or ❌ (blocked)
```

### Recovery: Correct Protocol

```
[ACTION] Writing BTI013 Communication, Protocols & Decision Records.md to disk
Topics: 8 (triggers, memory rules, dissent records) with infrastructure examples
Examples: Cloudkicker failover, Graphiti persistence, graceful degradation
Status: 70% complete (planning done, writing in progress)
ETA: 30 minutes

[Edit after completion] ✅ COMPLETE
Document: /home/nesbitt/projects/ig88/docs/bti/BTI013 Communication, Protocols & Decision Records.md
Gate: Document ready for your review (8 topics + worked example)
Next: Behavioral gate after approval (1 week: 3 completion reports + 1 dissent record + 1 trigger communication)
Thread: #backrooms (link to gate review discussion)
```

User's next action: Review BTI013, approve document gate, signal readiness for behavioral gate.

---

## Questions for Gate Review

1. **Trigger protocols:** Are the four tiers (T1-T4) and example formats clear enough to use operationally?

2. **Memory write rules:** Does the table (Decisions → Graphiti, Reasoning → Markdown, etc.) match actual practice, or need refinement?

3. **Dissent records:** Is the lightweight format practical for monthly retrospectives, or too heavy?

4. **Documentation protocol:** Should BTI013-style curriculum modules always be marked with `[ACTION] Writing {Title}` before completion, or is this overhead?

5. **Graphiti persistence blocker:** Should we treat Graphiti ingestion failure (Phase 0) as blocking decision record storage, or accept that decisions live in markdown + Matrix threads until fixed?

---

## Next Steps

**Document Gate:** This module (8 topics + worked example + questions)

**Behavioral Gate:** 1-week operational demonstration
- 3 completion reports using `[ACTION]` format with clear outcomes
- 1 decision record with minority dissent + planned retrospective
- 1 trigger communication (`[PROPOSE]` or `[REQUEST]`) with explicit approval thread

**Success Criteria:**
- All 8 topics demonstrated in actual infrastructure operations
- Chris reviews and approves document gate
- Behavioral gate execution shows protocols working in practice
- At least one decision record with dissent evaluated at 30-day retrospective

**Linked Modules:**
- BTI011 (Infrastructure & Service Operations) — incident examples, degradation band decisions
- BTI012 (Project Portfolio Strategy) — workload planning decisions, IG-88 trust elevation proposal
- Module 7 (BTI014, pending) — Retrospectives & Learning Systems

---

**End BTI013 Document Gate**
