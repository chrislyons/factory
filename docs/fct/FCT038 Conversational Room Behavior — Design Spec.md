# FCT038 Conversational Room Behavior — Design Spec

**Date:** 2026-03-23
**Status:** DESIGN ONLY — not for implementation this session
**Type:** Design Specification
**Related:** FCT033, FCT036, BKX037, BKX042

---

## Context

This spec was deferred from FCT033 Session 4. The conversational room behavior changes involve medium-risk sync filter modifications in the coordinator-rs polling loop. Implementing these during a session focused on Whitebox migration and identity anchoring would introduce unnecessary risk. The identity anchoring work (FCT033 Session 4 Section 0.2) must be proven stable before any sync filter changes are attempted.

---

## 1. all_agents_listen Room Flag + Room History Injection

Group rooms like Backrooms require all agents to observe messages, not just the mentioned agent. The `all_agents_listen` flag on a room configuration entry would cause the coordinator to forward all messages in that room to every agent's context, regardless of mention.

The existing `multi_agent_context_char_limit: 2000` setting already provides a truncation budget for injected room history. This section defines how that budget is allocated across agents and how the history window is managed (sliding window vs. summarization).

**Open questions:**
- Should history injection be per-poll or accumulated across polls?
- How does the char limit interact with the agent's own context window budget?

---

## 2. "Should I Respond?" Heuristic + Loop Prevention

When multiple agents observe the same room, each must independently decide whether to respond. Without a heuristic, agents will either all respond (noise) or none respond (silence).

**Proposed heuristic layers:**
1. Explicit @mention — always respond
2. Topic relevance — match message content against agent's domain keywords
3. Recency — if another agent already responded within N seconds, defer
4. Sender filtering — never respond to messages from other agents unless explicitly mentioned (loop prevention)

**Loop prevention** is the critical constraint. Agent A responding to Agent B responding to Agent A is a runaway failure mode. Sender filtering (ignore messages from bot users unless @mentioned) is the minimum viable guard.

---

## 3. Agent vs. Worker Contract

Are agents in group rooms peers-with-a-router or agents-routed-as-workers?

**Peers-with-a-router:** Each agent independently decides whether to act. The coordinator routes messages but does not assign work. Agents may disagree or duplicate effort.

**Agents-routed-as-workers:** The coordinator assigns responsibility for each message to exactly one agent. Other agents observe but do not act unless reassigned.

This distinction is load-bearing for the approval model, budget tracking, and loop control. The current architecture implicitly assumes agents-routed-as-workers (one agent handles one message), but conversational rooms push toward the peer model.

**Reference:** TX260315_0000-9A31 (Backrooms session exploring multi-agent dynamics).

---

## 4. Incoming Message Verification — Identity Confusion

Identity confusion occurs when an agent processes a message attributed to the wrong sender, or when the coordinator misattributes a message due to sync race conditions. This is fundamentally a sender-verification problem.

**Failure modes:**
- Agent responds to its own echoed message (self-loop)
- Agent attributes a message to Chris when it was from another agent
- Coordinator maps a Matrix user ID to the wrong agent identity

**Mitigations:**
- Verify `sender` field against the agent's own Matrix user ID before processing
- Cross-reference sender against the agent roster for identity resolution
- Log sender verification failures as circuit-breaker events

**Reference:** TX260225_1632-15C4 (identity confusion incident), CS8 (coordinator security finding).

---

## 5. Acknowledgment Protocol — Future Work

Workers must confirm receipt of dispatched messages. Without acknowledgment, the coordinator cannot distinguish between "agent is processing" and "message was lost." This enables:

- Retry logic for unacknowledged messages
- Accurate dispatch latency metrics
- Dead-letter detection (see Section 6)

**Design constraint:** Acknowledgment must not require a Matrix message (would create noise). Options include coordinator HTTP API callback, file-based signal, or in-band stream-json confirmation.

---

## 6. Dead-Letter Queue — Phase D Scope

Messages arriving during coordinator restart are currently lost. A dead-letter queue would persist undelivered messages and replay them on recovery.

**Scope:** This is Phase D work (FCT033). The coordinator must first have stable identity anchoring and reliable sync before adding persistence guarantees.

**Design options:**
- JSONL append log on disk, replayed on startup
- Matrix room as persistence layer (read-back unprocessed events on restart)
- SQLite queue table (aligns with GSD sidecar evolution)

---

## Prerequisites

1. **Identity anchoring must be proven stable** — FCT033 Session 4 Section 0.2 delivers inline prompt anchoring and identity file injection. These must run without identity confusion incidents for at least one full operational cycle before sync filter changes are introduced.
2. **All three agents online and responding** — recovery priorities (FCT029 Section 5) must be fully resolved.
3. **Coordinator-rs running on Whitebox** — no split-brain between Blackbox and Whitebox coordinators.

---

## References

[1] FCT033, "Whitebox Migration — Session Plans and Execution," 2026-03-23.

[2] FCT036, "Session 4 Final Report and Handoff," 2026-03-23.

[3] BKX037, "Agent Identity Architecture," 2026-02-15.

[4] BKX042, "Agent Lifecycle Commands and Health Scoring," 2026-02-20.

[5] TX260315_0000-9A31, Backrooms session transcript — multi-agent dynamics exploration.

[6] TX260225_1632-15C4, Identity confusion incident transcript.

[7] FCT029, "Factory Consolidated Plan — Architecture, Recovery, and Roadmap," 2026-03-22.
