# Next Steps Plan — Post-Session 4B

**Date:** 2026-03-23
**Status:** Ready for execution
**Context:** Sessions 1-4B complete. Agents have souls, tools, and stable infrastructure. House is clean.

---

## Three Independent Workstreams

These are unblocked and can proceed in any order. None depends on the others.

---

### Stream 1: Stability Observation (Passive — 7 Days)

**Purpose:** Prove identity anchoring holds in live conversation. Start the Phase D (megOLM) stability clock.

**What to do:** Nothing. Let agents run. Interact with them naturally in Matrix over the coming week. Observe:

- Do agents maintain their soul identity in extended conversation?
- Does identity confusion recur in shared rooms (Backrooms)?
- Does the coordinator stay stable (no crashes, no token expiry)?
- Does the watchdog fire any real alerts?

**Check-in points:**
- Day 3: Spot-check coordinator logs for errors beyond the known coord sync issue
- Day 7: If clean → Phase D gate is met. Schedule megOLM cutover per FCT033 Section 10.

**No session needed.** Just live with the system.

---

### Stream 2: Phase C Prep — Paper Trading Readiness

**Purpose:** Get IG-88 from "has tools" to "can execute a paper trade cycle."

**Run from:** Cloudkicker, `~/dev/factory/` with `--add-dir ~/dev/factory/agents/ig88`

**Pre-requisites confirmed:**
- [x] Jupiter API key in BWS
- [x] jupiter-mcp + dexscreener-mcp deployed on Whitebox
- [x] .mcp.json in IG-88 working directory
- [x] Solana wallets generated (trading pubkey in BW)
- [ ] Hot wallet funded ($200-800 USDC + ~0.05 SOL) — **USER ACTION**
- [ ] jupiter_price verified working end-to-end (B5 — still not confirmed)

**Session scope:**

1. **Verify B5 — Jupiter connectivity.** DM IG-88 in Matrix, ask it to check SOL price. If `jupiter_price` is not in AUTO_APPROVE_TOOLS, manually approve the tool call. Confirm the full chain: coordinator → Claude subprocess → .mcp.json → mcp-env.sh → BWS → jupiter-mcp → Jupiter API → price returned.

2. **Add read-only Jupiter/Dex tools to AUTO_APPROVE_TOOLS.** These are market data queries with zero execution risk:
   - `jupiter_price`, `jupiter_quote`, `jupiter_portfolio`
   - `dex_token_info`, `dex_token_pairs`, `dex_search`, `dex_trending`
   - `jupiter_swap` stays OUT (requires approval — it moves money)
   This is a coordinator source change on Whitebox (python3 targeted edit, not SCP).

3. **Run first paper trade cycle per FCT033 Section 8 / IG88010.** This is IG-88's first real analysis cycle:
   - Regime Detection → Scanner → Narrative → Governor
   - Record trade #1 in the validation log with the new schema (including `regime_label`)
   - Confirm the 25-trade checkpoint framework is set up for ongoing tracking

4. **Write FCT041 sprint report** with B5 results, AUTO_APPROVE_TOOLS changes, and first trade outcome.

**User actions required:**
- Fund hot wallet before step 3 (or use dryRun:true for pure paper mode — no real capital needed for paper trades)
- Approve jupiter_swap if it fires during the trade cycle

---

### Stream 3: FCT038 — Conversational Room Behavior

**Purpose:** Make agents feel like agents, not command-response bots.

**Gate condition:** Identity anchoring must be proven stable (Stream 1, ~7 days). Do not implement before then.

**Run from:** Cloudkicker, `~/dev/factory/` with `--add-dir ~/dev/blackbox`

**Session scope:**

1. **Read FCT038 in full.** The design spec covers 6 sections: all_agents_listen flag, "should I respond?" heuristic, agent vs worker contract, identity confusion prevention, acknowledgment protocol, dead-letter queue. Sections 5-6 are future work.

2. **Implement Section 1 — `all_agents_listen` room flag.** Coordinator sync loop change: when a room has this flag, forward all messages to every agent's context (not just the mentioned agent). Use existing `multi_agent_context_char_limit: 2000` for truncation budget.

3. **Implement Section 2 — "Should I respond?" heuristic.** The minimum viable version:
   - Explicit @mention → always respond
   - Message from another bot → never respond (loop prevention)
   - No mention + topic relevant to agent's domain → respond
   - No mention + not relevant → observe silently

4. **Implement Section 4 — Sender verification.** Prevent agents from responding to their own echoed messages. Cross-reference sender against agent roster.

5. **Test in Backrooms.** Send a message that's relevant to IG-88's domain (market question) without tagging anyone. IG-88 should respond; Boot and Kelk should observe. Then send a project management question — Boot should respond.

6. **Write FCT042 sprint report.**

**Risk:** Medium — sync loop filter changes can break agent routing if done wrong. The Session 3 experience (SCP overwrites, sync timeout issues) is a warning. Apply changes via targeted python3 edits on Whitebox, test incrementally.

---

## Recommended Sequencing

```
Now          Stream 1 starts (passive — just use the system)
When ready   Stream 2 (paper trading prep — ~2hr session)
Day 7+       Stream 3 (conversational rooms — ~3hr session, after stability gate)
Day 7+       Phase D (megOLM — separate session, after stability gate)
```

Stream 2 can happen anytime — even tomorrow. It's independent of the stability observation.

---

## Parked Items (Revisit Later)

| Item | When |
|------|------|
| Coord sync failure | If it becomes annoying or blocks approvals. Currently noise-only. |
| GitHub SSH on Whitebox | Next time git pull is needed on Whitebox. Try again — was working Mar 21. |
| BWS kebab-case audit | Next BWS session. Low priority. |
| matrix-mcp plists (Boot :8445, Coord :8448) | Not blocking anything. Coordinator talks to Pan directly. |
| Whitebox source divergence reconciliation | When coordinator-rs needs a significant code change. Not now. |
