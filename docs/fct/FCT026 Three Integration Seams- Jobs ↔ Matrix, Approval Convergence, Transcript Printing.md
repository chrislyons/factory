## FCT026 Three Integration Seams: Jobs ↔ Matrix, Approval Convergence, Transcript Printing

### 1. Jobs ↔ Matrix Threads: The Missing Link

Right now, jobs and Matrix conversations exist in **parallel universes**:

- **Jobs** live in `jobs/<domain>/job.DD.CCC.AAAA.yaml` → compiled to `jobs.json` → rendered in Portal
- **Matrix conversations** are tracked by `thread_id` (5-char generated ID like `f3g8s`) and `thread_root_event_id` (Matrix DAG reference)
- **Neither references the other.** A job card in the Portal has no idea which Matrix thread produced its work. A Matrix thread has no idea which job it's servicing.

The coordinator already generates a `thread_id` per dispatch (`coordinator.rs:1195`) and stamps it onto activity messages in Element (`[f3g8s] calling Read...`). But that ID is ephemeral — it exists only in `CoordinatorState` and dies when the session ends.

**The tightening move:**

```
job.20.200.0042.yaml          Matrix room: !ig88-room:matrix.org
┌─────────────────────┐       ┌─────────────────────────────────┐
│ id: job.20.200.0042 │       │ [f3g8s] Analyzing AAPL momentum │
│ thread_ids:         │◄─────►│ [f3g8s] Tool: mcp__ig88__trade  │
│   - f3g8s           │       │ ⚠️ ig88 needs approval [f3g8s]  │
│   - k7m2n           │       │ ✅ (approved)                    │
│ matrix_room: !ig88… │       │ [f3g8s] Trade executed           │
└─────────────────────┘       └─────────────────────────────────┘
```

This requires two additions:

**a) Coordinator writes thread→job binding.** When the coordinator dispatches a message to an agent, if the dispatch can be associated with a job ID (via room routing rules, or a `job:` tag in the triggering message), it writes the `thread_id` into the job's YAML file or a sidecar index. The binding is: *this thread_id was generated while servicing this job*.

**b) Portal renders the link.** Each job card gains a `thread_ids[]` field. Clicking a thread ID opens `https://app.element.io/#/room/!room_id:matrix.org/$thread_root_event_id` — a direct deep link into Element's thread view. You go from "job card showing status" to "the actual conversation that produced that status" in one click.

The inverse also works: in Element, the `[f3g8s]` tag in every activity message becomes a searchable anchor. You see `[f3g8s]` in a thread, you can grep for it in `jobs.json` to find which job it belongs to.

**What the coordinator already has:** `thread_id` generation, `thread_root_event_id` tracking per session, room→agent mapping. What's missing is the job→thread binding and persistence of that binding beyond the session lifetime.

### 2. Approval Convergence: One Signed Pipeline, Two Input Surfaces

Reading the approval code confirms the current state:

**Matrix path** (`coordinator.rs:1593-1689`):
1. Coordinator posts approval message to `COORD_APPROVAL_ROOM` with HMAC tag
2. Operator reacts ✅/❌ in Element
3. `process_reaction()` verifies HMAC, checks `approval_owner` sender
4. Writes `ApprovalRecord` to in-memory tracker
5. For `fs_approval` type: writes HMAC-signed `.response` file via `HmacSigner::write_approval_response()`

**Portal path** (`api.ts:97-101`):
1. Portal calls `POST /approvals/:id/decide`
2. GSD sidecar... does what exactly with this? It needs to reach back into coordinator state

The filesystem approval path (`coordinator.rs:1841-2072`) already solves this pattern beautifully. The coordinator scans `approval_dir` every 3 seconds for `.request` files and picks up `.response` files written by external processes. The Portal's sidecar just needs to use the same mechanism:

```
Portal "Approve" click
    → POST /approvals/:id/decide (sidecar)
    → sidecar writes {id}.response to approval_dir
      using same HMAC secret + write_approval_response() format
    → coordinator's fs_approval_scan picks it up (≤3 sec)
    → same ApprovalRecord, same HMAC verification
```

The sidecar needs access to the HMAC secret file (or a dedicated signing endpoint on the coordinator's future HTTP API on `:41950`). Either way, the approval artifact is byte-identical regardless of whether you tapped ✅ in Element or clicked "Approve" in Portal.

The `ApprovalDecision` enum should grow a `PortalApproved` / `PortalDenied` variant so the analytics tracker can distinguish provenance — you'll want to know what percentage of approvals come from each surface.

### 3. Transcript Printing: Matrix Room → Factory Logs

The coordinator already captures two transcript streams:

**a) Run events** (`run_events.rs`): Append-only JSONL per run at `~/.config/coordinator/runs/{run_id}.jsonl`. These are structured machine events — `ToolCall`, `ToolResult`, `SessionStart`, etc. The Portal already reads these via `GET /runs/:id/events` and renders them in `TranscriptTail`.

**b) Matrix room history**: The full human-readable conversation. This is *not* currently captured locally — it lives only in the Matrix DAG on the homeserver.

The gap is (b). You want to "print" room transcripts into Factory-local logs so you have a complete record without needing to query Matrix. Three approaches, in order of increasing integration:

**Approach 1: Periodic room export (simplest)**
A cron job or coordinator maintenance task calls Matrix's `/messages` API with a `since` token per room, appends to `logs/{agent_id}/transcript.jsonl`. Just message bodies, timestamps, senders. The Portal gets a new "Transcript" tab on agent detail pages that reads these files.

**Approach 2: Live tee during dispatch (coordinator-native)**
The coordinator already sees every message that flows through it — both inbound (user→agent) and outbound (agent→user via `drain_agent_activity`). It could tee these to a per-agent transcript log alongside the run event JSONL. This captures only messages during active sessions, but that's the interesting part.

**Approach 3: Structured transcript with cross-links (compound)**
Combine both: the coordinator tees live dispatch transcripts to `logs/{agent_id}/{thread_id}.md` as human-readable markdown. Each file is named by thread_id, and the job YAML links to it via `thread_ids[]`. Now you have:

```
Portal job card → thread_id → logs/ig88/f3g8s.md (local transcript)
                            → element://room/!ig88/thread/$event_id (live Element link)
```

The cross-app routing you mentioned — switching between Portal and Element — becomes concrete through these thread IDs. They're the **join key** between the two projections:

| Surface | What you see | Thread ID role |
|---------|-------------|----------------|
| Portal job card | Status, assignee, budget | Link to transcript + Element thread |
| Portal transcript tab | Rendered markdown of conversation | Navigable by thread_id |
| Element thread | Live conversation, approval reactions | Tagged with `[f3g8s]` in first message |
| Local log file | `logs/ig88/f3g8s.md` | Archival record, searchable |

### Putting it together: the compound integration map

```
                     ┌──────────────────────────┐
                     │     coordinator-rs        │
                     │                           │
                     │  dispatch ──► thread_id   │
                     │  approval ──► .response   │
                     │  activity ──► run JSONL   │
                     │  tee ──────► transcript   │
                     └─────┬──────────┬──────────┘
                           │          │
              ┌────────────▼──┐  ┌────▼───────────┐
              │  Matrix sync  │  │  Filesystem     │
              │  (3s poll)    │  │  (.response,    │
              │               │  │   .jsonl, .md)  │
              └───────┬───────┘  └────┬────────────┘
                      │               │
              ┌───────▼───────┐  ┌────▼────────────┐
              │   Element     │  │   GSD sidecar    │
              │               │  │   (:41911)       │
              │  • conversation│  │                  │
              │  • ✅/❌ react │  │  • GET /jobs.json│
              │  • [f3g8s] tag│  │  • GET /runs/:id │
              │               │  │  • GET /transcript│
              └───────────────┘  │  • POST /approve │
                                 └────┬────────────┘
                                      │
                                 ┌────▼────────────┐
                                 │   Portal        │
                                 │                  │
                                 │  • job cards     │
                                 │  • budget bars   │
                                 │  • approve btn   │
                                 │  • transcript tab│
                                 │  • → Element link│
                                 └──────────────────┘
```

The `thread_id` becomes the **universal join key** across all surfaces. It's already generated, already stamped into Matrix messages, already short enough to be human-readable. It just needs to be persisted into job records and used as the filename for transcript logs. That single change stitches jobs, approvals, conversations, and transcripts into one navigable compound interface.