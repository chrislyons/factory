# FCT031 Next Steps Forward

### Whitebox is further along than FCT029 recorded

**WHB006 (Phase 2b) is COMPLETE** — three services already migrated to Whitebox:

| Service | Port | Host | Status |
|---------|------|------|--------|
| FalkorDB | 6379 | **Whitebox** (Colima Docker) | LIVE |
| Graphiti MCP | 8444 | **Whitebox** | LIVE (uses MLX-LM on :8081 + Ollama :11434) |
| Pantalaimon | 8009 | **Whitebox** (launchd) | LIVE, Olm DB migrated from Blackbox |

This means Pantalaimon is **no longer on Blackbox** — it's on Whitebox. The Graphiti connection errors we saw earlier likely mean **MLX-LM port 8081 isn't running** on Whitebox (Graphiti depends on it for LLM calls).

### Inference servers are manual-start only

No launchd plists exist for MLX-LM ports 8080-8083. They must be started manually on Whitebox:
```
mlx_lm.server --model ~/models/Nanbeige4.1-3B-8bit --port 8080
mlx_lm.server --model ~/models/Qwen3.5-4B-MLX-8bit --port 8081
mlx_lm.server --model ~/models/LFM2.5-1.2B-Thinking-MLX-6bit --port 8082
mlx_lm.server --model ~/models/Qwen3.5-9B-MLX-6bit --port 8083
```

### Agent token restoration procedure changes

Since Pantalaimon is now on **Whitebox :8009** (not Blackbox), the token restoration curl commands need to target Whitebox's Pantalaimon instance. The token files still go on Blackbox in `~/.config/ig88/` where the coordinator reads them.

### Cross-signing will need re-running after megOLM

BKX065 cross-signing ceremony was for Pantalaimon device IDs. After native E2EE migration, new device IDs are generated — the ceremony must be re-run.

### Additional secrets already wired

The BKX explorer confirmed these are already in Bitwarden + age:
- Anthropic API key, OpenRouter API key, Qdrant API key, Graphiti API key, LunarCrush API key, Cloudflare API token, Matrix Pantalaimon tokens (all 4 agents)

**No traditional exchange APIs (Binance, IBKR, Alpaca) exist anywhere in the codebase.** IG-88 is entirely Solana/DeFi-native via Jupiter.

---

## Revised Action Sequence

### Phase A: Restore Agent Health

1. **SSH to Whitebox** — start MLX-LM servers (ports 8080-8083). This unblocks Graphiti.
2. **Verify Graphiti** responds after 8081 is running.
3. **SSH to Blackbox** — retrieve @ig88 and @kelk Matrix passwords from Bitwarden, login to Pantalaimon on **Whitebox** :8009, write token files to Blackbox `~/.config/ig88/`
4. Fix coordinator systemd `MATRIX_TOKEN_COORD_PAN` injection
5. Restart coordinator-rs, verify all 3 agents respond
6. `make sync` portal security fixes to Blackbox
7. Commit + push outstanding changes

### Phase B: IG-88 API Key Wiring

8. Obtain Jupiter API key from portal.jup.ag
9. Generate Solana trading keypair on Blackbox
10. Store in `~/.config/ig88/.env`
11. Fund hot wallet ($200-800 USDC + ~0.05 SOL)
12. Verify: `jupiter_price`, `jupiter_quote` connectivity

### Phase C: Paper Trading Validation (3-4 weeks)

13. 100-trade validation per IG88010/IG88006 framework

### Phase D: megOLM Cutover (after agent stability gate)

14. Only after agents stable for full operational cycle on Pantalaimon

---

## Outlying Issues

- **Graphiti down** — almost certainly because MLX-LM :8081 isn't running on Whitebox (Graphiti's LLM backend)
- **No launchd plists for MLX-LM** — manual start required; should create plists before going to production
- **Whitebox CLAUDE.md port table stale** — still shows FalkorDB/Pantalaimon/Graphiti as "Planned" when WHB006 completed them
- **BKX119 30-day cleanup overdue** — monolith `/home/nesbitt/projects/ig88` not removed
- **LFM2.5 tool-call adapter not built** (BKX080) — blocks Nan from entering coordinator dispatch loop
- **Duplicate models on Whitebox** (~27GB in `/Users/whitebox/Documents/local-models/`) need cleanup

---

Ready to proceed when you are. Phase A step 1 (SSH to Whitebox to start inference servers) is the logical first move — it unblocks Graphiti and sets the stage for everything else.