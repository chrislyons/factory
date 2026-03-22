## FCT025 The Compound Interface: Why Factory Has Two Faces

Your research vault already names the pattern. The "Agent Orchestration Layer" synthesis [1] identifies three coordination architectures: centralized orchestrator, skill-based dispatch, and Paperclip's three-layer coordination (coordination → polling → wakeups). Ethan Mollick's models/apps/harnesses framework [2] provides the vocabulary. The "Agent Framework vs Harness" decision page [3] explains why the harness layer — not the framework — is where value accrues.

Factory is a **compound interface** because coordinator-rs is a harness, not an app. It has no native UI. It needed two projection surfaces, and you built both:

### The two projections

```
                         coordinator-rs
                        (harness layer)
                              │
                 ┌────────────┴────────────┐
                 │                         │
           Matrix/Element              Portal/React
          (conversational              (structured
           projection)                 projection)
                 │                         │
         ┌───────┴───────┐          ┌──────┴──────┐
         │ dialogue       │          │ dashboards   │
         │ approvals      │          │ analytics    │
         │ ad-hoc commands│          │ task mgmt    │
         │ audit trail    │          │ budget viz   │
         │ E2EE           │          │ loop control │
         │ mobile/push    │          │ topology     │
         └────────────────┘          └─────────────┘
```

**Matrix** is the conversational projection — you talk to agents, they talk back, approvals happen inline, the DAG is the audit trail, Megolm provides E2EE. This is the interface you use when you need to *interact* with agents: ask questions, give instructions, approve trades.

**Portal** is the structured projection — you see all agents at once, filter jobs, visualize budgets, track loop iterations, read analytics. This is the interface you use when you need to *observe* the system: what's running, what's spent, what's blocked.

### Why Paperclip collapsed these and you shouldn't

Paperclip has only the structured projection (React dashboard). Scott Sparkwave's architecture [4] uses polling + wakeups + acknowledgment — all machine-to-machine protocols. The operator interacts exclusively through the dashboard. There's no conversational channel.

This works for Paperclip's "zero-human company" framing where the operator is a supervisor reviewing reports. It breaks for Factory's model where the operator is a **participant** — you're in the conversation, not watching from a control room.

The research vault's "Harness Engineering" topic page [5] captures the ACI thesis (rohit4verse): the Agent-Computer Interface is where value accrues, and it needs to be purpose-built. Factory's compound approach gives you *two* ACIs tuned for different cognitive modes:

| Mode | Interface | When |
|------|-----------|------|
| **Directive** — telling an agent what to do | Matrix | "IG-88, analyze the AAPL momentum cross" |
| **Supervisory** — checking system health | Portal | Glance at topology, budget bars, loop status |
| **Adjudicative** — approving actions | Either | Emoji in Element *or* button in Portal |
| **Investigative** — understanding what happened | Both | Transcript in Element, analytics in Portal |
| **Emergency** — something's wrong, intervene | Matrix | Portal down? Element still works on phone |

### The one architectural seam that needs welding: approval convergence

FCT020 (Security Audit) [6] flagged this at finding C2: "Approval decisions via Matrix reactions have no cryptographic verification on the Matrix path." The portal has the *inverse* problem — it can approve without HMAC signing.

Both paths need to produce the same artifact: an HMAC-signed `ApprovalRecord` on disk that the coordinator's filesystem scanner picks up. Today:

- **Matrix path:** emoji reaction → `process_reaction()` in coordinator.rs → writes `ApprovalRecord` (HMAC-signed)
- **Portal path:** `POST /approvals/:id/decide` → GSD sidecar → writes... what? Presumably the same file, but the signing happens where?

The fix: the sidecar's approval endpoint must use the same HMAC secret and produce byte-identical `ApprovalRecord` files. Both projections converge on a single signed approval pipeline. The coordinator doesn't care *which* surface generated the approval — it just reads signed files from disk.

### What this means going forward

You don't need to choose. The compound interface is the design. The question is whether new features get projected onto one surface or both:

| Feature | Matrix | Portal | Why |
|---------|--------|--------|-----|
| Budget override | `BudgetOverride` approval gate | Override button on `BudgetBar` | Both — mobile resilience |
| Loop start/stop | `!loop start <spec>` | Start/Abort buttons | Both — already built |
| Agent pause/resume | `!agent pause ig88` | Pause/Resume button | Both — already built |
| Transcript reading | Room history | `TranscriptTail` (read-only) | Matrix is authoritative, Portal is summary |
| New job creation | Not natural | `JobCombobox` | Portal only — structured data entry |
| Ad-hoc conversation | Room message | Not possible | Matrix only — that's what chat is for |

The compound architecture means each new capability gets a simple decision: "Is this conversational or structured?" If conversational → Matrix. If structured → Portal. If safety-critical → both, converging through signed artifacts.

Paperclip can't do this because they have no protocol layer. You can, because Matrix *is* the protocol and the portal is a lens on the same state.

---

### References

[1] Agent Orchestration Layer. `docs/patterns/Agent Orchestration Layer.md`. Projects vault synthesis.
[2] E. Mollick, "Guide to Which AI to Use in the Agentic Era." `TX260217_2049-2C8C`. Research vault.
[3] Agent Framework vs Harness. `docs/decisions/Agent Framework vs Harness.md`. Research vault decision page.
[4] S. Sparkwave, "Inter-Agent Communication and Task Orchestration in Paperclip." `TX260315_2045-8B49`. Research vault.
[5] Harness Engineering. `docs/topics/Harness Engineering.md`. Research vault topic page.
[6] FCT020 Factory Security Audit — Red-Hat Team Assessment. `docs/fct/FCT020`. Finding C2.