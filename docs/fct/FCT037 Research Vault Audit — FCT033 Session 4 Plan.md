# FCT033 Session 4 — Research Vault Audit Report

**Plan audited:** `~/.claude/plans/glowing-foraging-stroustrup.md`
**Method:** 4 parallel research agents, 3-4 compounding Qdrant searches each (16 total queries)
**Vault corpus:** 418 TX docs, 331 synthesis docs
**Date:** 2026-03-23

---

## Executive Summary

The plan correctly identifies all the right problems. Its execution mechanisms are too thin in two areas (identity anchoring, coordinator resilience) and miss one architectural property entirely (acknowledgment protocols). The watchdog design is sound but has a data-loss bug (`/tmp` state). Secrets handling aligns well with research. Seven concrete improvements follow.

---

## CRITICAL — Fix Before Executing

### 1. Identity Anchoring is Too Shallow (Plan 0.2)

**Plan proposes:** `"Your name is {NAME}. You are NOT {other agents}."`

**Research says:** Generic role labels produce zero statistically significant improvement. ExpertPrompting tested 162 roles across 4 LLM families on 2,410 questions — each generic label's effect was "largely random" [TX260219_1107-C234]. What activates performance is *depth of description* — past context, values, behavioral anti-patterns — not name tags.

**Additional problems:**
- **Position matters.** "Lost in the Middle" paper shows U-shaped attention. Identity content must be FIRST in the system prompt, not appended [TX260218_1112-4C50]. >20% accuracy drop for mid-context information.
- **Single-layer is insufficient.** Augment Code's production architecture uses a 4-layer identity stack (system prompt + tools + skills files + runtime context). One inline addition is the weakest possible intervention [TX260305_1635-CC12].
- **Self-declaration is half the problem.** CS8 from the Agents of Chaos red-team: Kimi accepted a spoofed owner identity in a new channel. The empirical failures show identity confusion is equally an *incoming-message verification* problem, not just self-identification [TX260225_1632-15C4].

**Recommendation:** Replace the shallow label with a deep identity block placed FIRST in each agent's system prompt. Reference the existing `soul/` and `principles/` files in `~/dev/blackbox/src/` — these already contain the depth the research demands. Add a negative-example section ("In past sessions, agents confused identities when X — do not repeat this"). For v2, design incoming message verification (sender identity anchoring), which is flagged as an open problem in Agent Security.

### 2. Watchdog State in /tmp Will Silently Fail (Plan Part 3)

**Plan proposes:** `/tmp/watchdog/<service>.fail` files for consecutive-failure tracking.

**Research says:** Utah Agent Harness [TX260302_1444-2250] argues that ephemeral `/tmp` state is the primary source of reliability failures in cron-based systems. An RP5 reboot during an active outage resets the consecutive-failure counter to zero — the second-failure alert silently fails to fire until the failure recurs post-reboot.

**Recommendation:** Move state to `~/.local/share/watchdog/` or `~/watchdog/state/`. Non-volatile path survives reboots. One-line change, prevents the watchdog from failing at its primary job.

---

## HIGH — Strongly Recommended Additions

### 3. Add Coordinator Crash Recovery Spec (Plan 0.1 / Execution Order)

**Research says:** The Orchestrator's Dilemma [TX260314_1706-38E1] — if 5 services each have 95% reliability, the chain has ~77%. The coordinator is the single most consequential node. Agent Orchestration Layer pattern (5 sources, high confidence) says: "Design for graceful degradation from the start, not as an afterthought."

**Gap in plan:** No mention of what happens to in-flight Matrix messages if the coordinator process dies during the `launchctl` restart. No dead-letter queue. No message replay.

**Recommendation:** Add a degradation section to the plan: (a) What happens to messages received during coordinator restart? (b) Does launchctl auto-restart on crash? (c) Should the watchdog monitor the coordinator process itself? The watchdog already monitors Whitebox services — adding a coordinator health endpoint is minimal incremental work.

### 4. Add Acknowledgment Protocol to Coordinator (Plan 0.1)

**Research says:** Paperclip's production architecture [TX260315_2045-8B49] includes explicit acknowledgment — every task assignment requires worker confirmation. Without it, dropped messages become invisible failures. This is especially high-cost for IG-88 (trading) where a silent drop could mean a missed market signal.

**Gap in plan:** Messages are routed to agents but there is no described contract for what happens if the agent is unavailable, slow, or produces no response.

**Recommendation:** Define an ack contract: worker must confirm receipt within N seconds, else coordinator logs a dead-letter and optionally retries. Even a simple "message delivered to agent process" confirmation prevents silent drops.

---

## MEDIUM — Design Improvements

### 5. Clarify Agent vs. Worker Contract (Plan 0.2 / 0.3)

**Research says:** Agent Identity and Soul Architecture synthesis draws a sharp distinction — "Sub-agents are function calls: spec in, result out. They need the values of the system but not a full identity" [Agent Identity synthesis, 21 TX sources]. But Boot, IG-88, and Kelk have persistent identity (`soul/`, `principles/` files) and are architecturally agents, not stateless workers.

**Tension:** The coordinator routes to them as workers (message in, response out), but their identity files treat them as full agents. This conflation affects how the system prompt should be structured and what the conversational room behavior spec (FCT037) should assume.

**Recommendation:** Add a one-paragraph clarification to FCT037's design scope: are these agents-routed-as-workers (coordinator owns the conversation, agents are tools) or peers-with-a-router (agents own their conversations, coordinator is infrastructure)? The protocol surface differs meaningfully and determines whether conversational room behavior is a routing problem or an agent autonomy problem.

### 6. Watchdog Has No Watchdog (Plan Part 3)

**Research says:** The compound failure math applies to the watchdog itself [TX260314_1706-38E1]. If the cron job silently stops (RP5 cron daemon failure, script error), all 5 monitored services become invisible.

**Recommendation (v1-appropriate):** Add a heartbeat file — the watchdog writes a timestamp to `~/watchdog/last-run` on every execution. A separate, trivially simple check (could even be a manual `ssh blackbox 'stat ~/watchdog/last-run'` in the verification checklist) confirms the watchdog is alive. For v2: `systemd` timer instead of cron provides built-in failure detection.

### 7. Log Alert Delivery Attempts (Plan Part 3)

**Research says:** Agent Orchestration Layer pattern requires acknowledgment protocols to prevent silent task drops. If the Matrix HTTP call fails (network partition, bot auth expired), the watchdog alert is silently lost.

**Recommendation:** Log every alert attempt (success or failure) to a local file regardless of Matrix delivery status. One line of bash: `echo "$(date) ALERT $service $http_code" >> ~/watchdog/alerts.log`.

---

## VALIDATED — No Changes Needed

| Plan Element | Research Verdict | Key Source |
|---|---|---|
| Deferring conversational room behavior to FCT037 | Strongly supported — Skills-First principle confirms simple routing before heuristic behavior | TX260315_0000-9A31 |
| Alert-on-second-failure threshold | Validated — maps to fail2ban consecutive-event pattern | TX260217_0918-191D |
| BWS kebab-case audit (13 secrets) | Strongly supported — external secrets as production baseline is ecosystem convergence | TX260226_1908-BD35 |
| Token loaded from file on RP5 | Correct — matches agent-vault injection-boundary pattern | TX260219_0839-43CA |
| Read-only GitHub deploy key | Supported — MCP GitHub server hijack case argues for minimum-viable-access scoping | TX260307_1130-7262 |
| Silence-is-ok alerting model | Validated in production agent systems | TX260219_0724-B404 |

---

## Research Gaps (Not Covered by Vault)

These items in the plan have no supporting or contradicting evidence in the research vault:

- **Graphiti secret rotation in Keychain-blocked SSH environments** — novel to this infrastructure, no vault coverage
- **Blue-green deployment / launchctl service lifecycle** — outside vault domain
- **Matrix message continuity during coordinator switchover** — not addressed in any TX doc
- **2-minute cron interval justification** — no research basis found; appears reasonable but is not empirically grounded

---

## TX Documents Cited

| TX ID | Title | Relevance |
|---|---|---|
| TX260219_1107-C234 | Agent Design / ExpertPrompting | Identity label ineffectiveness |
| TX260218_1112-4C50 | Lost in the Middle | System prompt position effects |
| TX260305_1635-CC12 | Augment Code Architecture | Multi-layer identity stack |
| TX260225_1632-15C4 | Agents of Chaos Red-Team | Identity spoofing failure modes (CS8, CS11) |
| TX260226_1007-BCEB | AI-to-AI Jailbreak | 97% jailbreak rate, $0.02/attack |
| TX260315_0000-9A31 | Claude Subagents vs Agent Teams | Coordination surface minimization |
| TX260314_1706-38E1 | Orchestrator's Dilemma | Compound failure math, SPOF risk |
| TX260302_1444-2250 | Utah Agent Harness | Durable state vs /tmp volatility |
| TX260315_2045-8B49 | Paperclip Architecture | Acknowledgment protocols |
| TX260217_0000-3EDD | DeepMind Delegation Framework | Recovery logic vs retry logic |
| TX260219_0724-B404 | OpenClaw Health Checks | Alert-on-break pattern |
| TX260226_1908-BD35 | OpenClaw External Secrets | External secrets as production baseline |
| TX260219_0839-43CA | agent-vault | Placeholder injection-boundary pattern |
| TX260307_1130-7262 | MCP Connection Guide | GitHub credential scoping |
| TX260208_0000-C2H8 | LLMs Cannot Keep Secrets | Architectural secret separation |
| TX260217_0918-191D | OpenClaw Security Hardening | Consecutive-failure thresholding |
| TX260319_0049-0A7E | Council of High Intelligence | Anti-recursion enforcement |
| TX260220_2121-C43C | Multi-Agent Token Burn | 1.4B tokens in 2 weeks |
| TX260302_0948-3771 | Software Assembly Line | Monitoring vs tracing distinction |
| TX260317_0024-A4A7 | OpenClaw to Hermes Migration | Migration fit assessment |

---

*Report generated for handoff to planning/build agent. All findings are grounded in the research vault corpus — no external claims without TX citation.*
