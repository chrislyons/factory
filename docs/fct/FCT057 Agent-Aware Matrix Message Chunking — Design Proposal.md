# FCT057 Agent-Aware Matrix Message Chunking — Design Proposal

**Status:** Proposal — design for discussion, not yet implemented
**Date:** 2026-04-08
**Related:** FCT055 (post-mortem that surfaced the truncation bug), matrix_legacy.rs:42-47 (current 30k hard cap with latent UTF-8 panic)

## 1. Problem

Matrix has a hard protocol limit of 65,535 bytes per `m.room.message` event. Once JSON-encoded with `body` (plaintext) + `formatted_body` (HTML) + envelope, the usable plaintext budget is approximately 30,000-32,000 characters before the total event exceeds the ceiling and the server rejects it. The coordinator (`matrix_legacy.rs:42`) currently enforces this via a hard 30,000-char truncate with a trailing `[truncated, N chars]` marker.

This limit has not yet been observed to bite in practice because a more restrictive upstream cap — mlx-vlm's `DEFAULT_MAX_TOKENS = 256` — was capping responses at ~1KB long before they could approach Matrix's 64KB ceiling. That upstream cap was fixed 2026-04-08 (hermes-serve.py now passes `max_tokens` from profile config; profiles now set `max_tokens: 32768`). With the upstream cap gone, agent responses can legitimately approach and exceed Matrix's event-size budget, and the existing truncate becomes visible.

Three distinct issues:

1. **Silent truncation is bad UX.** When a long response gets cut at exactly 30,000 chars with `[truncated, N chars]` appended, the reader loses the content with no recourse. The agent believes it sent the full response; the reader sees half of it.
2. **The truncate uses byte-slicing on a UTF-8 string** (`matrix_legacy.rs:241-248` and `:547-557`), which panics on multi-byte characters at the boundary. Currently unreachable because responses are short; becomes live as soon as responses routinely exceed the cap.
3. **Paragraph, code-block, and table boundaries get cut mid-structure** if the truncate ever fires — unusable output.

The fix needs to (a) preserve semantic structure across message boundaries, (b) give the agent deliberate control over where breaks happen, (c) fall back gracefully when the agent doesn't chunk on its own, and (d) not panic on UTF-8.

## 2. Design Space Considered

Three candidate mechanisms were evaluated:

### 2.1 Automatic coordinator-level chunking (rejected as sole mechanism)

The coordinator detects oversized bodies and automatically splits on paragraph boundaries before sending N consecutive Matrix events. Zero agent work.

**Why not sufficient alone:** The chunker has to guess good break points. Code blocks, tables, nested markdown, and multi-line quotes can break at awkward points. The reader has to mentally reassemble. The agent is unaware and doesn't learn to structure long responses for segmentation.

### 2.2 Tool-call chunking (rejected as primary mechanism)

Add a native `send_matrix_message(body, final=false)` tool the agent calls explicitly. Clean in principle but requires either patching Hermes upstream (scope creep, not our code) or building an MCP server that can reach back into the coordinator's Matrix session to inject messages (architecturally awkward because the Matrix session lives in a Rust process while the MCP server would be Python stdio).

### 2.3 Agent-emitted break marker (RECOMMENDED)

The agent emits a distinctive separator token in its output at semantic break points. The coordinator parses the separator in the outgoing body, splits on it, sends N messages consecutively in the same thread, strips the marker. The separator is *content* the agent produces, not a structured tool call schema that small models can mangle. Works for Gemma 4 E4B reliably.

Proposed marker: **`\n\n<<<MATRIX_BREAK>>>\n\n`** — distinctive, unlikely to appear in real content, visually separable, survives markdown rendering if a marker ever leaks through.

Alternative considered: `\n\n⸻MATRIX⸻\n\n` (horizontal-bar Unicode). Rejected because the Unicode character could introduce edge cases in byte-level comparisons.

## 3. Recommended Architecture

**Hybrid: agent-emitted markers as the primary path, paragraph-boundary auto-split as the safety net.**

### 3.1 Agent path (primary)

Agents emit `\n\n<<<MATRIX_BREAK>>>\n\n` at semantic boundaries in long responses. Soul-file guidance (see §5) teaches them when and how:

- When the response has multiple distinct sections (report header, body, conclusion)
- Between a large code block and its explanation
- Between a table and its interpretation
- Before and after any content exceeding ~20-25 paragraphs

Short responses emit no marker and flow as a single message, exactly as today.

### 3.2 Coordinator path

`matrix_legacy.rs::send_message` and `::send_thread_reply` are extended to handle the marker:

```rust
const MATRIX_BREAK_MARKER: &str = "\n\n<<<MATRIX_BREAK>>>\n\n";
const MAX_BODY_CHARS: usize = 32_000;  // raised from 30_000, still under Matrix ceiling

fn split_for_matrix(body: &str) -> Vec<String> {
    // Phase 1: split on explicit agent markers
    let chunks: Vec<&str> = body.split(MATRIX_BREAK_MARKER).collect();

    // Phase 2: for each chunk, if still too large, apply paragraph-boundary
    // recursive split as a safety net
    let mut out = Vec::new();
    for chunk in chunks {
        if chunk.chars().count() <= MAX_BODY_CHARS {
            out.push(chunk.to_string());
        } else {
            out.extend(recursive_split_by_boundary(chunk, MAX_BODY_CHARS));
        }
    }

    out.into_iter().filter(|s| !s.trim().is_empty()).collect()
}

fn recursive_split_by_boundary(body: &str, max: usize) -> Vec<String> {
    // Try boundaries in order of preference:
    // 1. paragraph break "\n\n"
    // 2. line break "\n"
    // 3. sentence end ". " (with care for abbreviations)
    // 4. word break " "
    // 5. hard cut at char_indices().nth(max) — guaranteed UTF-8 safe
    // Return Vec<String> of pieces each ≤ max chars.
}
```

Each chunk is sent as a separate Matrix event in the same thread. No prefix markers ("1/3", "2/3") needed — thread adjacency makes the sequence visible. Optional affordance: trailing `…` on all but the last chunk.

### 3.3 UTF-8 safety

The existing `&body[..MAX_RESPONSE_LENGTH]` byte-slicing at `matrix_legacy.rs:244` and `:550` is replaced with a `char_indices()`-based slice that guarantees the cut lands on a UTF-8 boundary:

```rust
fn char_safe_slice(body: &str, max_chars: usize) -> &str {
    let cut = body.char_indices()
        .nth(max_chars)
        .map(|(i, _)| i)
        .unwrap_or(body.len());
    &body[..cut]
}
```

This eliminates the latent panic that becomes reachable as soon as long responses land.

## 4. Implementation Plan

### 4.1 Coordinator changes

File: `coordinator/src/matrix_legacy.rs`

- Raise `MAX_RESPONSE_LENGTH` from `30_000` to `32_000` (char-based, not bytes)
- Add `MATRIX_BREAK_MARKER` constant
- Add `split_for_matrix()` helper with the hybrid logic above
- Add `recursive_split_by_boundary()` helper for safety-net splitting
- Add `char_safe_slice()` helper for UTF-8-safe byte slicing
- Modify `send_message()` at ~line 241: replace the truncate-and-send block with a loop that sends each chunk from `split_for_matrix(body)` as a consecutive Matrix event
- Modify `send_thread_reply()` at ~line 547: same pattern

### 4.2 Tests

File: `coordinator/src/matrix_legacy.rs` (unit tests at the bottom) or `coordinator/tests/matrix_chunking.rs`

Test cases:
1. Single-message passthrough — short body with no marker returns a single chunk
2. Two-way split on marker — body with one marker returns two chunks, marker stripped
3. N-way split on marker — body with N-1 markers returns N chunks
4. Oversized chunk fallback — single chunk exceeding `MAX_BODY_CHARS` triggers recursive paragraph-boundary split
5. UTF-8 multi-byte characters at the boundary — emoji, CJK characters, combining marks; no panic; cut on char boundary
6. Empty marker handling — `<<<MATRIX_BREAK>>>` at start or end of body produces no empty chunks
7. Mixed marker and oversize — body with marker where one resulting chunk is still too large applies both passes
8. Adjacent markers — `<<<MATRIX_BREAK>>><<<MATRIX_BREAK>>>` collapses to a single break (filter empty chunks)

### 4.3 Soul-file guidance

File: `agents/{boot,ig88,kelk}/CLAUDE.md`

Add a new section "Long Responses in Matrix" under the Tools or Output section:

> **Long responses in Matrix.** Matrix has a per-message size limit (~32,000 characters after HTML rendering). When your response will run long — more than ~20 paragraphs, a large code dump, or multiple distinct sections — break it explicitly by emitting `<<<MATRIX_BREAK>>>` on its own paragraph at semantic boundaries. Good break points: between a report's sections, after a large code block or table, between analysis and recommendation. Bad break points: mid-sentence, mid-code-block, mid-table.
>
> The coordinator splits on these markers and sends each part as a separate message in the current thread. You do not need to number the parts ("1/3", "2/3") — Matrix's thread rendering makes the sequence visible. The marker itself is stripped from the output.
>
> Do NOT use the marker for short responses. It is noise when not needed. Most responses should fit in a single message and should not contain the marker at all.

### 4.4 Deployment

1. `cargo test` in `coordinator/` — all new tests pass, existing 78 tests still pass
2. `cargo build --release`
3. `launchctl kickstart -k gui/502/com.bootindustries.coordinator-rs` — restart coordinator
4. Verify from log that startup is clean
5. Send a test prompt to Boot or Kelk in a private room: "Write a 5000-word essay on X. Break it into sections with `<<<MATRIX_BREAK>>>` between sections." Verify the response arrives as N messages in the thread.

## 5. Alternatives Considered and Rejected

- **Automatic chunking only (no agent control):** §2.1, rejected. Guesses break points badly; code blocks split mid-structure.
- **Native Hermes tool for send_matrix_message:** §2.2, rejected. Requires patching upstream Hermes; scope creep; doesn't cleanly connect the Python MCP layer to the Rust Matrix session.
- **File upload fallback for very long content:** for responses exceeding even the chunked ceiling, upload as a .md file attachment and send a notice. Deferred — not needed at current response sizes, revisit if 32k char chunks start stacking beyond 5-6 parts.
- **Server-side rendering with scroll affordances:** out of scope for Matrix as a protocol; would require a custom client. Not considered.

## 6. Open Questions

1. **Should the marker include optional section titles?** e.g., `<<<MATRIX_BREAK: Methodology>>>` where the title becomes the new message's thread prefix? Cleaner for skimming, more for the agent to do. **TBD — start without titles, add if needed.**
2. **Should there be an upper bound on chunk count?** An agent could emit 50 markers and produce 50 messages in a single turn. Probably want a sanity ceiling of ~10-15 parts, warn+merge beyond that. **TBD.**
3. **Trailing `…` affordance on all-but-last chunks:** adds a visual "more to come" cue. Low cost, arguably noisy. **TBD — leave off initially, add if user finds the thread ambiguous.**
4. **Does this interact with activity-drain thread notices?** The coordinator already posts intermediate `m.notice` events during tool-call narration (at `coordinator.rs:2099-2103`). Long final responses + intermediate notices could produce a busy thread. Probably fine; note for Phase 3 observation. **TBD.**
5. **Streaming alternative:** when mlx-vlm streaming is eventually re-enabled (after PRs #974/#964 merge or are cherry-picked), the coordinator could stream tokens to Matrix and produce messages as natural paragraphs complete, making the marker less necessary. **Deferred — depends on mlx-vlm fix landing.**

## 7. Rollout

- **Phase 1:** Land the coordinator changes behind a feature flag (env var or config) — default off, opt-in via an agent-config.yaml setting. Allows soak testing before broad enable.
- **Phase 2:** Add soul-file guidance to one agent first (probably Boot, most verbose). Observe whether Boot starts using the marker appropriately.
- **Phase 3:** If Phase 2 is clean, enable by default and add guidance to IG-88 and Kelk. Remove the feature flag.
- **Phase 4:** Retrospective — was the agent usage pattern sensible? Did the safety-net auto-split ever fire? Did any chunk get rejected by Matrix? Iterate on the guidance based on observed behavior.

## 8. References

[1] Matrix Specification, "m.room.message event size limit," https://spec.matrix.org/latest/client-server-api/#size-limits
[2] FCT055, "IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening," 2026-04-08, §10 truncation investigation
[3] mlx-vlm `DEFAULT_MAX_TOKENS = 256`, `mlx_vlm/generate.py:34`
[4] Coordinator truncation site, `coordinator/src/matrix_legacy.rs:42-47, 241-248, 547-557`
