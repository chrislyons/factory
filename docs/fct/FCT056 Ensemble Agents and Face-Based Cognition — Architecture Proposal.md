# FCT056 Ensemble Agents and Face-Based Cognition — Architecture Proposal

> *"Each agent a swirling, self-organizing ensemble of faces, following a conductor through the symphonies (and wash) of its intellect."*
> — Chris, 2026-04-08

**Status:** Proposal — vocabulary and shape for discussion, not an implementation spec
**Date:** 2026-04-08
**Related:** FCT046 (Provider Failover Chain) — partially superseded by this doc; FCT054 (E4B consolidation); FCT055 (overnight post-mortem, §10 mlx_vlm PR findings); IG88011 (cloud bake-off T1/T2/T3)

---

## 1. Motivation

The vocabulary in this document is a **flow vocabulary**. The terms below — current, tide, turn, eddy pool, conductor — name the system in terms of flow states because the system *is* a flow system, not a structure with process happening to it. An agent is not a static box that emits messages; it is moving substance that pools, circulates, commits, and flushes. Naming the parts in motion-language is load-bearing: it changes what we look at when we debug, what we measure, and what we treat as the unit of work. Restraint matters here — the metaphor is concentrated in §1–§3.5 and then used operationally as technical vocabulary in the engineering sections that follow.

The current multi-model vocabulary in the workspace is hierarchical. IG88011 [4] assigned models to **Tiers** (T1 fast filter, T2 calibrated, T3 deep analysis). FCT046 [3] framed multi-provider setups as a **Failover Chain** — a primary with fallbacks, ranked by priority. Both framings encode an implicit claim: the non-primary models are *degraded* alternatives, reached for when the primary fails or can't keep up.

Two things have changed since those docs landed.

First, FCT055 §10.3 [2] proved that E4B is not a weak model. The overnight failure was the mlx_vlm streaming response framing (PRs #974 and #964), not Gemma 4 E4B's cognitive capacity. Once those patches are cherry-picked — or with the streaming-off workaround validated in FCT055 — the 4B local model is genuinely capable of the work IG-88 is doing, not a stopgap. The "small model as fallback floor" intuition is wrong for our setup.

Second, Chris's critique on 2026-04-08: calling the 31B a "fallback" or a "Tier 2" distorts how we *reach* for it. A primary-with-fallbacks architecture treats the secondary as a failure mode. But the 31B isn't a failure mode — it's a **peer consultant** IG-88 should reach for *deliberately*, when the stakes or ambiguity warrant the extra latency and cost. The architecture should make that reach feel like consultation, not escalation-because-something-broke.

This document proposes a vocabulary and a structural pattern to replace the tier/cascade framing for agent-internal cognition. It supersedes FCT046 §2 (provider failover chain) *for the case of agent-internal multi-model use*. FCT046's provider-chain code is still the right answer for coordinator-level inference resilience — that's a different problem.

## 2. The Vocabulary

**Flow.** The moving substance of the system — messages, inference, tool calls, reactions, all of it in motion. Example: "the flow through IG-88 last night was mostly reflex-face turns with two deliberative consults."

**Current.** The direction an agent's active reasoning is pointed at any given moment; a state-noun. Example: IG-88's current is set on a BTC regime question and stays there until the question is resolved or displaced.

**Tide.** The rhythmic, total shift of that direction, with an *incoming* phase (gathering context, reaching sideways for faces) and an *outgoing* phase (committing to a response, producing output). Example: on the incoming tide of a trading decision IG-88 pulls in market state, memory, and the deliberative face; on the outgoing tide it commits to a single recommendation.

**Turn.** The event where a tide shifts and a different face becomes load-bearing; a verb-form. Example: when the reflex face's confidence drops below threshold, the tide turns and the deliberative face takes over the current.

**Eddy pool.** A region where flow slows, circulates, and accumulates significance — scale-free, occurring within a face, between faces, or across rooms. Example: an unresolved ambiguity pooling in the reflex face until enough context arrives for the tide to turn.

**Conductor.** A *role* (governing flow), not a named entity. Both Coord and individual agents play this role at different scales: Coord conducts the workspace, an agent conducts its own ensemble. Example: Coord routes a Matrix message to IG-88; inside IG-88, the reflex face conducts the consultation with the deliberative face.

**Wash.** The ephemeral flow that passes through a face without catching — inference produced, briefly used, discarded. Most of what the system generates is wash, and that is correct; only the flow that slows into an eddy pool becomes committed thought. Example: the reflex face produces 10k tokens analyzing a regime question; 9.8k of them are wash, and the 200 that stuck were the actual signal.

**Ensemble agent.** An agent whose cognition is produced by multiple cooperating models rather than a single monolithic LLM call. Each of the three factory agents (Boot, IG-88, Kelk) becomes an ensemble agent. Example: IG-88 is a single agent identity with a local E4B face, a cloud 31B face, and a memory-recall face, any of which can be invoked within a single Matrix turn.

**Face.** A named thinking surface within an ensemble agent. Faces are **peers**, not layers — any face can invoke any other. A face might be a fast local model, a larger cloud model, a domain-specialist fine-tune, or a retrieval system that isn't an LLM at all. No face is architecturally "primary"; there is only the one the agent reached for first given the stimulus. Example: IG-88's reflex face (E4B on `:41988`) handles a message, then consults its deliberative face (31B via OpenRouter) when it encounters an ambiguous trading signal.

## 3. The Resilient-Node Property

Every face must be independently disposable. The agent should degrade gracefully, not stop. This matters more than it sounds:

- **Overnight autonomy.** If IG-88 runs autonomously for eight hours and an intermediate face becomes unreachable at hour three, the agent must keep working. Under a cascade model ("primary = 31B, fallback = E4B"), losing the primary means losing the session; under an ensemble model, the reflex face was already doing most of the work and just loses one channel of consultation.
- **Debuggability.** When something is wrong, we want to be able to turn faces off one at a time without fear. A cascaded architecture makes each face a potential single-point-of-failure; an ensemble architecture makes each face a *capability* that can be individually suspended for testing.
- **Bio-inspired framing, restrained.** The analogy is neural redundancy and graceful degradation — losing a region narrows function rather than halting thought. That's the only framing nod this section makes; the rest is engineering.

The testable invariant: **for every face F in an agent's ensemble, the agent must still be able to respond to a basic Matrix DM with F unreachable.** Phase 3 smoke-tests this explicitly.

## 3.5 Two Scales: Flow and Ricochet

The flow vocabulary (tides, currents, eddies, turns) describes thought *within* an agent well. Cognition inside a single ensemble agent is continuous: context circulates, ambiguity pools, the tide turns, a face commits. There is no discrete event boundary inside a reasoning pass — it is one moving substance.

At the workspace scale — messages moving between users, rooms, agents, tools — the system is better described as a pinball machine. Chris's framing: *signal-in > bounce-around > signal-out*. Each encounter between a message and a bumper (coordinator dispatch, face inference, MCP tool call, Matrix reaction) is a discrete event that changes the trajectory. The coordinator's poll loop at `coordinator.rs:795-821` is the physics of the table: it is the thing that makes one bounce into the next.

These are the same system at different scales. Within-agent cognition is continuous flow; workspace infrastructure is discrete ricochet. FCT056 lives primarily at the agent-cognition scale and uses the flow vocabulary throughout, but pinball/bounce-around language is fair game when the subject is infrastructure — the two views are compatible because they describe the same machine seen at different resolutions.

The bounce-around is not connective tissue between the interesting parts — the bounce-around IS the system.

## 4. Wiring Options in Hermes

Parallel research into Hermes's internals (FCT055 §10 sibling investigation) answered the aux-slot question definitively: **Hermes's `auxiliary:` config is a fixed-schema map with exactly eight named slots** (`vision`, `web_extract`, `compression`, `session_search`, `skills_hub`, `approval`, `mcp`, `flush_memories`), each hardwired to a specific internal subsystem. You cannot declare `auxiliary.deliberative:` and have any LLM-facing tool route to it. The Hermes resolver at `auxiliary_client.py:1513` technically accepts arbitrary keys, but there is no tool exposed to the model that takes a slot name and dispatches a prompt to it — every call site passes a hardcoded literal string. Aux slots are internal plumbing, not a generic dispatch surface.

Hermes's `delegation:` config is also singular — one global override pair, no per-task routing. The `mixture_of_agents` tool exists but hardcodes four frontier OpenRouter models at line 63 of `mixture_of_agents_tool.py` and gives the LLM no parameters to reconfigure them. Neither is a usable mechanism.

This collapses the design space. Option (A) "native Hermes aux slots" is off the table. Three options remain:

### (A) MCP-server-as-consultant — RECOMMENDED

Expose each non-reflex face as a tool on a local MCP server. The reflex face calls the tool the same way it calls `search_files`: `consult_deliberative(query: str, context?: str) -> response`. The MCP server wraps an OpenAI-compatible client pointed at whatever endpoint backs that face (OpenRouter for 31B, a future local Qwen 2.5 14B, whatever). The agent sees a named, schema'd, deliberate consultant path — which is exactly the "reach sideways" semantics we want.

This is the officially supported Hermes extension point. `mcp_servers:` in the profile config is documented at `hermes_cli/mcp_tool.py:15-34`, supports stdio and remote transports, and per-server tool filtering via `tools.include`/`tools.exclude`. Profiles are fully isolated `HERMES_HOME` directories, so declaring the consultant in IG-88's profile doesn't affect Boot or Kelk — clean scoping.

Pseudo-config sketch (`~/.hermes/profiles/ig88/config.yaml`):

```yaml
# Reflex face (unchanged from FCT054)
model: /Users/nesbitt/models/gemma-4-e4b-it-6bit
base_url: http://127.0.0.1:41988/v1
provider: custom

mcp_servers:
  consultants:
    command: python3
    args:
      - /Users/nesbitt/dev/factory/scripts/face-consultant-mcp.py
    env:
      FACE_NAME: deliberative
      FACE_MODEL: google/gemma-4-31b-it
      FACE_PROVIDER: openrouter
    tools:
      include: [consult_deliberative]
```

The MCP server itself is small — ~50–100 lines of Python that registers one stdio-MCP tool, validates inputs, proxies to the OpenAI-compatible endpoint, returns the completion text as tool output. Adding a second face later is a second env-scoped MCP server entry. The pattern generalizes: `consult_analyst`, `consult_fast`, `consult_vision` are all just more MCP entries.

**Surprise finding from the research that shapes this design:** MCP sampling is bidirectional. An MCP server IG-88 connects to can request LLM completions *from IG-88's own model* via `sampling/createMessage` — meaning an untrusted server could burn IG-88's deliberative-face budget. The consultant MCP server must explicitly set `sampling.allowed_models: []` (empty list) to refuse reverse-sampling requests. Noted for implementation.

### (B) LiteLLM router on `:41010`

FCT workspace docs already plan LiteLLM on `:41010`. A router hop in front of all inference lets any agent call any model by name. Most general, most flexible for the workspace as a whole. But LiteLLM alone doesn't solve the ensemble-agent problem: the agent runtime still needs a way to say "this next call goes to a different model than my default," which in Hermes brings you back to option (A) anyway. LiteLLM is complementary infra — the right answer for workspace-wide inference routing (unified rate limiting, budget tracking, provider abstraction) — but not a substitute for the consultant-MCP pattern for agent-internal cognition. Worth standing up later regardless.

### (C) Second Hermes instance + HTTP dispatch

Run a second Hermes profile on a different port pointed at the 31B, call it from the reflex profile via HTTP. This gives the consultant its own tools (the 31B could itself have MCP servers, memory access, etc.) and its own session history, which may be interesting long-term for memory-specialist faces. But it is operationally heavier than (A) — a whole second agent process to host one model — and degrades into (A) in practice because you still need a dispatch wrapper. Skip for Phase 2; revisit if we want the deliberative face to have its own persistent context.

**Decision:** Option (A), MCP-server-as-consultant. Aux slots are off the table, (B) is complementary infra (not a mechanism), (C) is operationally heavier than needed. The MCP consultant is the officially supported extension point and gives the agent exactly the semantics we want: a named, schema'd, deliberately-invoked peer.

## 5. IG-88's Initial Ensemble

First ensemble configuration for IG-88, scoped to Phase 2:

| Face | Model | Venue / Port | Trigger | Latency (est.) | Cost |
|---|---|---|---|---|---|
| **reflex** | Gemma 4 E4B 6-bit | local, `mlx-vlm-ig88` on `:41988` | every message, every tool cycle; the default | ~1s warm per turn per FCT054 [1] | $0 |
| **deliberative** | Gemma 4 31B | OpenRouter `google/gemma-4-31b-it` via `consult_deliberative` MCP tool | tide-turn triggers in §6 | ~15s first token per IG88011 [4] | $0.001–0.002 per consult |
| **memory** | Qdrant / Graphiti | `:41440` (Graphiti MCP), `:41460` (Qdrant MCP) | "what do I already know about X?" | <1s | $0 |
| **analyst** (future, not Phase 1) | TBD domain-specialist | TBD | deep research, not wired in Phase 1 | — | — |

Notes:

- The **memory** face is not an LLM but is shaped the same way: the reflex face invokes it via tool call, gets back a response, incorporates it. Including it in the ensemble makes the pattern consistent — all consultations are the same move, different destinations.
- The **analyst** face is a placeholder for a future domain-specialist model (possibly a quant fine-tune from tuning-wizard, per FCT054 Future Work #4). Reserving the slot in the vocabulary now, not the config.
- **The reflex face is doing most of the work.** This is by design. The deliberative face is *expensive* — a consultation is an act, not a default. The triggers in §6 should produce maybe one consultation per N reflex turns where N is large, not a consultation on every decision.

## 6. When the Tide Turns — Soul-Level Guidance

To be added to IG-88's soul file (`agents/ig88/CLAUDE.md`) under a new section "Face Consultation":

- **Low-confidence trading signal.** When the tide of a trading decision turns ambiguous — reflex confidence below the threshold in `config/trading.yaml` (default 0.7) — consult the deliberative face before executing. Reflex decides cheap cases; deliberative gets the marginal ones.
- **Ambiguous user message.** When a message from Chris contains ambiguity that the reflex face cannot resolve on its first internal pass, consult the deliberative face with a distilled question rather than ping-ponging interpretations.
- **Regime-change signal.** When a possible regime shift is detected — MACRO state change, volatility spike, correlation break — the tide turns and the deliberative face takes over the current. Consequences of acting on a stale regime outweigh the consult cost.
- **Stalled tide on a tool-call loop.** When reasoning has been circling the same tool call for more than three iterations without converging, the tide has stalled — consult the deliberative face *instead of* retrying a fourth time. Thrashing is the signal that the reflex face is stuck; consult rather than burn tokens in circles. (Directly addresses the overnight 03:01 failure mode from FCT055 §3.)
- **Incoming tide vs outgoing tide for high-stakes actions.** On the incoming tide — while still gathering context for a trade above the auto-approval threshold — reach sideways freely; pull in memory, deliberative, whatever clarifies the picture. On the outgoing tide — while committing to the approval request Chris will see — only the trusted faces should speak, and the deliberative face must have signed off. Gives Chris a pre-reviewed proposal instead of raw reflex output.

**The agent decides.** No hardcoded router lives in code. The guidance above is principles the reflex face learns to apply, the same way it learns to follow any other soul-file rule. If the pattern lands and we want to harden a particular trigger into code later, we can — but the vocabulary stays the same.

## 7. Rollout Plan

- **Phase 1 — Vocabulary adoption.** Land this document. Link from FCT054 and FCT055 as "supersedes the tier/cascade framing for agent-internal cognition." No code changes. Chris reacts, we iterate on the terms.
- **Phase 2 — IG-88 deliberative face wired.** Build `scripts/face-consultant-mcp.py`. Register in `~/.hermes/profiles/ig88/config.yaml` under `mcp_servers.consultants`. Add the Face Consultation section to `agents/ig88/CLAUDE.md`. No new models required — 31B via OpenRouter is already accessible.
- **Phase 3 — Smoke test.** Low-stakes query in the IG-88 Training room: *"Explain the current BTC regime to me, and consult the deliberative face before answering."* Verify the consult happened (turn log shows the `consult_deliberative` tool call), verify the response is materially different from reflex-alone, verify the resilient-node property by killing the OpenRouter path mid-session and confirming IG-88 still responds on reflex alone.
- **Phase 4 — Extend to Boot and Kelk.** Different ensembles per role. Boot's deliberative face might be a code-tuned model. Kelk's might be a model with stronger reflective/long-context capability. Each agent's tide-turn guidance lives in its own soul file. The `face-consultant-mcp.py` script is reused; only env vars change per profile.

## 8. Open Questions

1. **Do "ensemble agent" + "face" + "current" + "tide" + "turn" + "eddy pool" land?** Chris to react. Alternatives considered and rejected: "cut" (too static, imports fixity the metaphor is trying to get rid of), "facet" (less evocative than face), "tier" (priority-distorting), "submodel" (hierarchical), "brain region" (too twee), "escalation protocol" (procedural, not rhythmic), "conductor" as a *named entity* (Chris chose not yet — Coord stays as the label, though "conductor" remains valid as a ROLE both Coord and individual agents play at different scales).
2. **Context sharing between faces.** Should the deliberative face see the reflex face's full conversation history, or a distilled query? Full history is expensive (3k+ tokens of Hermes system prompt plus conversation) and may confuse the larger model with reflex-specific framing. Distilled queries are cheaper and cleaner but lossy. Probably: distilled by default, full-history-on-request as an escape hatch. **TBD.**
3. **Cost budget per consultation.** Current bake-off cost for 31B is ~$0.001 per short query per IG88011 [4]. If IG-88 consults 20 times overnight, that's $0.02. If the reflex face gets stuck in a consult loop (thrashing at the meta level), that could balloon. Need a daily consult budget enforced in the MCP server. **TBD — suggest starting at $1/day as a sanity ceiling.**
4. **Raw output vs summary layer.** Should the reflex face see the deliberative face's raw response, or should there be a summary/normalization layer between them? Raw preserves information; summary reduces confusion and cost. Probably raw for Phase 2, revisit if it causes issues.
5. **MCP sampling lock-down.** The consultant MCP server must set `sampling.allowed_models: []` to refuse reverse-sampling requests, or an untrusted upstream could burn the deliberative budget. Confirmed as an implementation requirement for Phase 2.
6. **Does this vocabulary eventually absorb the coordinator's provider-chain logic from FCT046 §2?** No — they solve different problems. FCT046's provider chain handles *infrastructural* resilience (what to do when the inference endpoint is down). This doc handles *cognitive* composition (what to do when you want a second opinion from a peer). They coexist; the provider chain is underneath each face.
7. **Retrofitting FCT054/FCT055 language.** Both docs use tier/fallback framing in places. A mechanical pass to align them with ensemble/face vocabulary should happen *after* this doc's vocabulary is approved, not as part of it. Tracked as a follow-up.

## 9. References

[1] FCT054, "Local E4B Model Consolidation — All Agents on Gemma 4 E4B 6-bit," factory docs, `docs/fct/FCT054 Local E4B Model Consolidation — All Agents on Gemma 4 E4B 6-bit.md`, Apr. 2026.

[2] FCT055, "IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening," §10.3, factory docs, `docs/fct/FCT055 IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening.md`, Apr. 2026.

[3] FCT046, "Provider Failover Chain and Hermes Integration Architecture," §2, factory docs, `docs/fct/FCT046 Provider Failover Chain and Hermes Integration Architecture.md`, Apr. 2026. (Partially superseded by this document for agent-internal cognition; remains authoritative for coordinator-level provider resilience.)

[4] IG88011, "Cloud Model Bake-Off Results," §2 Tier Assignments, `agents/ig88/docs/ig88/IG88011 Cloud Model Bake-Off Results.md`, Apr. 2026. (T1/T2/T3 tier framing superseded by ensemble/face vocabulary; bake-off data still authoritative.)

[5] Hermes Agent documentation — Configuration, NousResearch. [Online]. Available: https://hermes-agent.nousresearch.com/docs/user-guide/configuration

[6] Hermes Agent documentation — Integrations / Providers, NousResearch. [Online]. Available: https://hermes-agent.nousresearch.com/docs/integrations/providers

[7] P. Cuadra et al., "mlx-vlm PR #974 — Strip tool-call markup from streamed delta.content," GitHub. [Online]. Available: https://github.com/Blaizzy/mlx-vlm/pull/974

[8] P. Cuadra et al., "mlx-vlm PR #964 — Set finish_reason to 'tool_calls' when the model emits tool calls," GitHub. [Online]. Available: https://github.com/Blaizzy/mlx-vlm/pull/964
