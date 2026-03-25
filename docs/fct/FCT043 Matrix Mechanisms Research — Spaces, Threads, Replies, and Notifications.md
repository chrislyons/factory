# FCT043 Matrix Mechanisms Research -- Spaces, Threads, Replies, and Notifications

**Date:** 2026-03-24
**Type:** Research / Recommendation
**Status:** Research complete -- no code changes
**Related:** FCT038, FCT042, BKX037

---

## 1. Current Pain Points

Based on the coordinator-rs codebase (`coordinator.rs`, `matrix_legacy.rs`) and operational experience:

| # | Pain Point | Impact |
|---|-----------|--------|
| P1 | **MSC3440 relation conflicts** -- threading off events that already carry `m.relates_to` produces server errors ("Cannot start threads from an event with a relation"). Current workaround: detect error and fall back to plain message. | Responses silently lose threading context. |
| P2 | **DM threading disabled entirely** -- DMs send plain messages because threading adds visual noise and hits relation conflicts more often (DM replies chain naturally). | Acceptable, but means DM conversations have no structure in Element's thread panel. |
| P3 | **No room organization** -- 10+ rooms appear as a flat list in Element sidebar. Chris must mentally map rooms to domains. | Cognitive load; easy to miss messages in rarely-checked rooms. |
| P4 | **Verbose tool activity noise** -- `m.notice` thread posts for tool calls clutter room timelines, especially in Backrooms where multiple agents operate. | Important messages buried under tool-call noise. |
| P5 | **No notification control** -- all `m.text` messages in group rooms ping Chris equally. Agent chatter and error reports have the same notification weight as actionable requests. | Alert fatigue; missed approvals. |
| P6 | **No multi-agent room coordination** -- FCT038 designed but unimplemented. Agents in shared rooms (Backrooms) lack "should I respond?" logic, `all_agents_listen`, and loop prevention. | Only @mentioned agent responds; no ambient awareness. |
| P7 | **Room aliases missing** -- rooms are identified by opaque `!room_id:matrix.org` strings in config and logs. | Debugging difficulty; no human-friendly room references. |

---

## 2. Quick Wins (Immediate, low risk)

### QW1: Create a "Boot Industries" Space

**What:** Create a Matrix Space (room with `type: m.space`) to group all agent rooms.

**How it works:** A Space is just a Matrix room with `"type": "m.space"` set at creation time. Child rooms are added via `m.space.child` state events on the Space, and rooms optionally declare their parent via `m.space.parent` state events. Element renders Spaces as collapsible sidebar groups with nested room lists.

**Implementation:**
1. Create a room with `POST /createRoom` including `"creation_content": {"type": "m.space"}`.
2. For each existing room, send an `m.space.child` state event from the Space pointing to the room's `room_id`.
3. Optionally, from each child room, send an `m.space.parent` state event pointing back to the Space (requires sufficient power level in the child room).

**Benefit:** All 10+ rooms collapse into a single "Boot Industries" sidebar entry in Element. Rooms become discoverable via the Space hierarchy rather than requiring manual joins.

**Risk:** None. Spaces are purely organizational; they do not alter room behavior, permissions, or message routing. The coordinator does not need to know about Spaces at all.

### QW2: Set Room Aliases

**What:** Create human-readable aliases for all rooms.

**How it works:** Matrix supports room aliases (e.g., `#backrooms:matrix.org`) via the directory API. Aliases are stored server-side and resolve to `!room_id`. A room's canonical alias is set via the `m.room.canonical_alias` state event.

**Implementation:**
```
PUT /_matrix/client/v3/directory/room/#backrooms:matrix.org
  {"room_id": "!actual_room_id:matrix.org"}
```

Then set the canonical alias on the room:
```
PUT state event m.room.canonical_alias
  {"alias": "#backrooms:matrix.org"}
```

**Suggested aliases:**
- `#backrooms:matrix.org` -- Backrooms
- `#trading:matrix.org` -- Trading Zone
- `#system-status:matrix.org` -- System Status
- `#training:matrix.org` -- Training Room
- `#general:matrix.org` -- General (may already exist)

**Benefit:** Logs, config files, and debug output become human-readable. Element displays the alias as the room name fallback.

### QW3: Use `m.mentions` for Targeted Notifications

**What:** Add the `m.mentions` field to coordinator-generated messages to control who gets pinged.

**How it works:** Matrix spec v1.7+ defines `content.m.mentions` with two fields:
- `user_ids`: array of Matrix user IDs who should be notified (triggers `.m.rule.is_user_mention` push rule)
- `room`: boolean, if true, notifies all room members (triggers `.m.rule.is_room_mention`)

When `m.mentions` is present, the legacy `contains_display_name` rule is bypassed -- only explicit mentions trigger notifications.

**Implementation in coordinator:**
```json
{
  "msgtype": "m.text",
  "body": "Task complete: ...",
  "m.mentions": {
    "user_ids": ["@chris:matrix.org"]
  },
  "m.relates_to": { ... }
}
```

For tool activity (`m.notice` messages), include an empty `m.mentions: {}` to suppress all user-mention notifications.

For approval requests, include Chris's user ID in `m.mentions.user_ids` to ensure the ping lands.

**Benefit:** Approval requests ping Chris. Tool activity, error summaries, and agent-to-agent chatter do not. This is the single highest-impact change for notification quality.

### QW4: Dedicated Error/Status Room

**What:** Create a `#errors:matrix.org` room for error reports, with Chris's push rules set to mute it.

**How it works:** The coordinator currently posts errors inline in whichever room the agent was working in. A dedicated room separates error noise from conversation flow. Chris can set a per-room push rule to `dont_notify` via Element settings (or API):

```
PUT /_matrix/client/v3/pushrules/global/room/{error_room_id}
  {"actions": ["dont_notify"]}
```

**Benefit:** Errors are captured and searchable but do not pollute conversation rooms or trigger notifications. The coordinator can still post a brief "[error logged to #errors]" notice in the original room for traceability.

---

## 3. Medium-Term Improvements (Architectural changes)

### MT1: Sub-Spaces for Domain Separation

**What:** Create sub-spaces within the Boot Industries Space:
- **System** (sub-space): System Status, Errors, General
- **Trading** (sub-space): Trading Zone, Training Room, IG-88-specific rooms
- **Projects** (sub-space): Claudezilla, Orpheus SDK, project-specific rooms

**How it works:** Spaces support nesting. A sub-space is just another `m.space` room added as a child of the parent Space via `m.space.child`. Element renders these as nested collapsible groups.

The `/hierarchy` API endpoint (`GET /rooms/{roomId}/hierarchy`) traverses the full tree, supporting `max_depth`, `limit`, and `suggested_only` parameters. Clients paginate with a `from` token.

**Benefit:** Domain-level organization that scales. New project rooms automatically slot into the right sub-space.

### MT2: Task-Per-Thread Pattern

**What:** Adopt a convention where each coordinator dispatch (task) creates a dedicated thread in the appropriate room, rather than threading off the user's message.

**Current behavior:** The coordinator threads off the incoming event's `event_id` (or its existing thread root). This is correct per MSC3440 but results in threads anchored to arbitrary messages.

**Proposed behavior:**
1. When the coordinator starts processing a task, it sends a **thread anchor message** to the room: `"[task:f3g8s] Boot processing: <brief description>"`
2. All subsequent tool activity and the final response thread off this anchor event.
3. The main timeline stays clean -- only anchor messages and non-threaded responses appear.

**Thread JSON structure (reference):**
```json
{
  "m.relates_to": {
    "rel_type": "m.thread",
    "event_id": "$anchor_event_id",
    "is_falling_back": true,
    "m.in_reply_to": {
      "event_id": "$anchor_event_id"
    }
  }
}
```

Key fields:
- `rel_type: "m.thread"` -- identifies this as a thread reply
- `event_id` -- always points to the **thread root** (anchor), never to a mid-thread message
- `is_falling_back: true` -- tells clients "the `m.in_reply_to` is just for fallback rendering, not a true reply within the thread." Set to `false` when replying to a specific message within the thread.
- `m.in_reply_to.event_id` -- for fallback clients that don't understand threads; should point to the most recent message being replied to (or the root if falling back)

**MSC3440 constraint:** The anchor event MUST NOT itself carry an `m.relates_to` relation, or all thread replies to it will fail. This is why the coordinator must send a fresh, relation-free anchor rather than threading off arbitrary incoming events.

**Benefit:** Eliminates P1 (relation conflicts) entirely. Every thread root is guaranteed clean. Thread panel in Element shows a clear list of tasks.

### MT3: Threaded Read Receipts

**What:** Use thread-aware read receipts so that unread indicators work per-thread.

**How it works:** Matrix supports `m.read` receipts with an optional `thread_id` field. When a client sends a read receipt for a threaded event, the server tracks read position per-thread separately from the main timeline.

```
POST /_matrix/client/v3/rooms/{roomId}/receipt/m.read/{eventId}
  {"thread_id": "$thread_root_id"}
```

The coordinator should send `m.read` receipts for each thread it processes, so Element shows threads as "read" once the agent has responded.

**Benefit:** Chris can glance at the thread panel and see which tasks have been handled (read) vs. pending (unread).

### MT4: Per-Agent Notification Profiles via Push Rules

**What:** Configure push rules so that:
- Approval requests always notify (override rule matching `m.mentions` with Chris's user ID)
- Agent `m.notice` messages (tool activity) never notify (already default for notices)
- Error room is muted (room-level rule)
- Agent-to-agent messages in shared rooms do not notify

**Push rule architecture (priority order):**

| Kind | Purpose | Evaluated |
|------|---------|-----------|
| Override | Highest priority, unconditional | First |
| Content | Match message text patterns | Second |
| Room | Per-room rules | Third |
| Sender | Per-sender rules | Fourth |
| Underride | Default fallback rules | Last |

**Recommended rules:**

1. **Sender rules** for each agent (`@boot:matrix.org`, `@ig88:matrix.org`, etc.) with action `dont_notify` -- suppresses routine agent messages.
2. **Override rule** for events containing `m.mentions.user_ids` matching Chris -- always notify with sound (overrides sender rules).
3. **Room rule** for error/status rooms -- `dont_notify`.

This means: agents are quiet by default, but when the coordinator explicitly `m.mentions` Chris (approval requests, task completions, errors requiring attention), the notification breaks through.

### MT5: Implement FCT038 Multi-Agent Room Behavior

The research confirms that Matrix mechanisms alone cannot solve the multi-agent coordination problem. Spaces, threads, and push rules handle organization, structure, and notification. But the core questions from FCT038 -- "should I respond?" heuristic, loop prevention, all_agents_listen -- are coordinator-level logic that operates above the Matrix protocol layer.

**Matrix mechanisms that support FCT038:**
- **Threads** isolate agent work so one agent's verbose output does not pollute another agent's context
- **`m.mentions`** lets agents explicitly hand off to each other (`"m.mentions": {"user_ids": ["@ig88:matrix.org"]}`)
- **`m.notice`** type for agent-generated content helps clients distinguish agent chatter from user messages
- **Room power levels** can restrict which agents can send messages vs. only read (observer role)

**What Matrix cannot do:**
- Decide which agent should respond to an unaddressed message
- Prevent response loops between agents
- Inject room history into agent context windows
- Manage per-agent context budgets

These remain coordinator responsibilities as specified in FCT038.

---

## 4. Matrix Mechanism Reference

### 4.1 Spaces

| Property | Detail |
|----------|--------|
| Room type | `m.space` (set in `creation_content.type` at room creation) |
| Child link | `m.space.child` state event (key = child room ID, content = `{"via": ["matrix.org"], "order": "01"}`) |
| Parent link | `m.space.parent` state event on child room (key = parent space ID) |
| Hierarchy API | `GET /rooms/{roomId}/hierarchy` -- traverses tree, returns `rooms[]` with `room_id`, `name`, `num_joined_members`, `children_state` |
| Permissions | Standard room power levels. Adding children requires power to send `m.space.child` state events. |
| Sub-spaces | A child of a Space can itself be a Space (`m.space` type). Nesting is unlimited. |
| Ordering | `order` field in `m.space.child` content (string, lexicographic sort). |
| Suggested rooms | `suggested` boolean in `m.space.child` content -- Element highlights these for new joiners. |
| Restricted joins | Rooms can use `join_rule: "restricted"` with `allow` conditions referencing Space membership, enabling "join any room in this Space" patterns. |
| Element UX | Spaces appear as collapsible sidebar groups. Users can browse Space hierarchy, see room previews, and join rooms without an invite. |

### 4.2 Threads (MSC3440)

| Property | Detail |
|----------|--------|
| Relation type | `m.thread` |
| Thread root | The event referenced by `m.relates_to.event_id`. Must NOT itself have an `m.relates_to` relation. |
| Reply within thread | Set `is_falling_back: false` and `m.in_reply_to.event_id` to the specific in-thread message being replied to. |
| Fallback mode | Set `is_falling_back: true` and `m.in_reply_to.event_id` to the thread root. Clients that do not support threads render this as a plain reply. |
| Validation | Servers reject thread replies where the root event carries any `m.relates_to`. Error: "Cannot start threads from an event with a relation." |
| Aggregation | Servers bundle `m.thread` relations on the root event, providing `latest_event` and reply count. |
| List endpoint | `GET /rooms/{roomId}/threads` -- returns all thread roots in a room with pagination. |
| Read receipts | `m.read` receipts can include `thread_id` to track per-thread read position. |
| Notifications | Thread replies follow normal push rules. `m.notice` type suppresses notifications by default. |
| Current coordinator usage | `send_thread_message()` for tool activity (m.notice, is_falling_back: true); `send_thread_reply()` for final response (m.text, is_falling_back: false). Fallback to plain message on relation conflict. |

### 4.3 Replies (m.in_reply_to)

| Property | Detail |
|----------|--------|
| Mechanism | `m.relates_to.m.in_reply_to.event_id` -- NOT a `rel_type`, but a sub-object within `m.relates_to`. |
| Standalone use | When used without `rel_type: "m.thread"`, creates a simple reply chain. Element renders with quoted preview. |
| Combined with threads | When used inside a thread relation, `is_falling_back` controls whether it is a true in-thread reply or just fallback rendering. |
| Fallback body | Spec recommends including a plaintext fallback of the replied-to message in the body (prefixed with `> `). Modern clients ignore this and render from the referenced event. |
| Agent use case | **Replies are ideal for DM conversations** where threading is disabled. The coordinator could use `m.in_reply_to` on DM responses to create visual reply chains without full threading. |

### 4.4 Rooms

| Property | Detail |
|----------|--------|
| DM indicator | `m.direct` account data event maps user IDs to room IDs. Not a room property -- it is per-account metadata. |
| Current DM detection | Coordinator uses member count (count == 2 means DM). This is a heuristic; `m.direct` would be more reliable but requires account data API call. |
| Aliases | `PUT /directory/room/#alias:server` to create; `m.room.canonical_alias` state event to set preferred alias. |
| Power levels | `m.room.power_levels` state event. Fields: `users` (per-user levels), `events` (per-event-type send thresholds), `events_default`, `state_default`, `ban`, `kick`, `invite`. Default user level is 0; room creator gets 100. |
| Room types | Set via `creation_content.type`. Only `m.space` is formally specified. Custom types (e.g., `m.agent_workspace`) are allowed but clients will not render them specially. |

### 4.5 Notifications and Push Rules

| Property | Detail |
|----------|--------|
| m.mentions | `content.m.mentions.user_ids` (array of MXID strings) and `content.m.mentions.room` (boolean). Triggers `.m.rule.is_user_mention` / `.m.rule.is_room_mention` push rules. |
| m.notice suppression | Default push rules do NOT generate notifications for `msgtype: m.notice`. This is why the coordinator uses m.notice for tool activity. |
| Rule kinds | Override > Content > Room > Sender > Underride (evaluation order). First match wins. |
| Conditions | `event_match` (field pattern), `contains_display_name`, `room_member_count`, `sender_notification_permission` |
| Actions | `notify`, `dont_notify`, `set_tweak` (sound, highlight) |
| Per-room mute | `PUT /pushrules/global/room/{roomId}` with `{"actions": ["dont_notify"]}` |
| Per-sender mute | `PUT /pushrules/global/sender/{userId}` with `{"actions": ["dont_notify"]}` |
| API | `GET/PUT/DELETE /pushrules/global/{kind}/{ruleId}` for CRUD; `/pushrules/global/{kind}/{ruleId}/enabled` to toggle. |

---

## 5. Specific Recommendations for Agent Topology

### Recommended Architecture

```
Boot Industries (Space)
+-- System (Sub-space)
|   +-- #general:matrix.org        (human + all agents, general chat)
|   +-- #system-status:matrix.org  (all agents, status/health)
|   +-- #errors:matrix.org         (NEW -- error sink, muted for Chris)
|   +-- #approvals:matrix.org      (coord + Chris, approval workflow)
+-- Trading (Sub-space)
|   +-- #trading:matrix.org        (ig88 + coord + Chris)
|   +-- #training:matrix.org       (ig88 + boot + coord + Chris)
+-- Projects (Sub-space)
|   +-- #backrooms:matrix.org      (all agents, multi-agent collaboration)
|   +-- #claudezilla:matrix.org    (boot + coord + Chris)
|   +-- #orpheus:matrix.org        (boot + coord + Chris)
+-- DM rooms (not in Space -- Element shows DMs separately)
    +-- Chris <-> Boot
    +-- Chris <-> IG-88
    +-- Chris <-> Kelk
    +-- Chris <-> Coordinator
```

### Implementation Priority

| Priority | Change | Effort | Impact |
|----------|--------|--------|--------|
| 1 | **QW3: Add `m.mentions` to coordinator messages** | 1 hour | Fixes notification noise (P5). Highest ROI. |
| 2 | **QW1: Create Boot Industries Space** | 30 min | Fixes room organization (P3). One-time setup. |
| 3 | **QW2: Set room aliases** | 20 min | Fixes debugging legibility (P7). One-time setup. |
| 4 | **QW4: Create #errors room** | 30 min | Fixes error noise (P4). Small coordinator change to route errors. |
| 5 | **MT2: Task-per-thread anchors** | 3 hours | Eliminates relation conflicts (P1) permanently. Coordinator change. |
| 6 | **MT4: Push rule configuration** | 1 hour | Complements QW3 with sender-level muting. |
| 7 | **MT1: Sub-spaces** | 30 min | Scales organization. Do after Space is proven useful. |
| 8 | **MT3: Threaded read receipts** | 2 hours | Nice-to-have. Requires coordinator to track receipt state. |
| 9 | **MT5: FCT038 multi-agent rooms** | Large | Separate project. Matrix mechanisms support it but do not solve it. |

### Key Insight: Coordinator vs. Protocol Responsibilities

Matrix provides the structural primitives (Spaces for organization, threads for conversation branching, mentions for notification targeting, push rules for filtering). The coordinator's job is to use these primitives correctly:

- **Organization:** Spaces and aliases are purely client-side UX. The coordinator does not need to interact with them at all.
- **Threading:** The coordinator already handles threading. The task-per-thread anchor pattern (MT2) is the main improvement -- it eliminates relation conflicts by guaranteeing clean thread roots.
- **Notifications:** Adding `m.mentions` to coordinator-generated events (QW3) is the single most impactful change. Combined with `m.notice` for activity and push rules for muting, this gives Chris granular control.
- **Multi-agent:** Matrix cannot solve the "who responds?" problem. That is coordinator logic (FCT038).

---

## 6. Implementation Log

### Session 2026-03-24: Three changes shipped

**QW3: m.mentions (DONE)**
- Added `Mentions` struct to `matrix_legacy.rs` with `user_ids: Vec<String>` and `room: bool`
- `send_message()` and `send_thread_reply()` accept `mentions: Option<&Mentions>>`; `None` emits empty `m.mentions: {}` (suppresses all mention notifications)
- `send_thread_message()` hardcodes empty `m.mentions: {}` (tool activity never pings)
- Approval requests pass `Mentions { user_ids: [approval_owner] }` — these ping Chris
- All other coordinator messages pass `None` — silent
- 4 new tests added (47 total)

**MT2: Task-per-thread anchors (DONE)**
- Added `send_anchor()` to `MatrixClient` — sends `m.notice` with empty `m.mentions`, no relations
- Coordinator dispatch (group rooms only) sends `"⚡ <agent_name>"` anchor, threads all activity off the anchor's event_id
- Anchor is guaranteed relation-free — permanently eliminates MSC3440 "Cannot start threads from an event with a relation" errors
- DM rooms unchanged (no threading)
- Existing relation-conflict fallback in `send_thread_message`/`send_thread_reply` kept as defense-in-depth

**"Invalid API key" root cause (DONE)**
- `/Users/nesbitt/.mcp.json` on Whitebox had 4 MCP servers pointing at retired Blackbox (100.87.53.109): qdrant-mcp (:8446), research-mcp (:8447), matrix-boot (:8445), matrix-coord (:8448)
- Fixed to Whitebox localhost (100.88.222.111): qdrant-mcp (:8442), research-mcp (:8443), matrix-boot (:8448), matrix-coord (:8440)
- The error was NOT coming through the coordinator's relay paths — Boot's Claude CLI was hitting dead Blackbox endpoints and emitting "Invalid API key" as a text block, which Boot then sent to Matrix via its own MCP
- Blackbox coordinator also killed (was still running despite being "retired")

**Infra checks platform fix (DONE — bonus)**
- Root cause: `infra.rs` hardcoded `/usr/bin/docker`, `/usr/bin/systemctl`, `/usr/bin/tailscale` — all missing on macOS (Whitebox)
- Added config fields: `infra_docker_containers`, `infra_systemd_services`, `infra_launchd_services`, `infra_tailscale_peers` (all `Option<Vec<String>>`, fallback to hardcoded defaults)
- `InfraChecker::new()` now takes `&Settings`
- Binary resolution: `find_docker()` and `find_tailscale()` probe multiple paths (Homebrew, /usr/local, /usr/bin, fallback to PATH)
- Platform-aware service checks: `check_platform_services()` runs launchd on macOS (when targets configured), systemd on Linux (when `/usr/bin/systemctl` exists)
- Added `ServiceType::Launchd` variant + `check_launchd_services()` using `/bin/launchctl list`

---

## References

[1] Matrix Specification v1.17, Client-Server API, "Threading" module. https://spec.matrix.org/latest/client-server-api/#threading

[2] Matrix Specification v1.17, Client-Server API, "Spaces" module. https://spec.matrix.org/latest/client-server-api/#spaces

[3] Matrix Specification v1.17, Client-Server API, "Push Notifications" module. https://spec.matrix.org/latest/client-server-api/#push-notifications

[4] Matrix Specification v1.17, Client-Server API, "Forming relationships between events." https://spec.matrix.org/latest/client-server-api/#relationships-between-events

[5] Matrix Specification v1.17, Client-Server API, "User and room mentions." https://spec.matrix.org/latest/client-server-api/#user-and-room-mentions

[6] FCT038, "Conversational Room Behavior -- Design Spec." Internal.

[7] FCT042, "Error Filter Centralization and Thread Strategy Overhaul." Internal.
