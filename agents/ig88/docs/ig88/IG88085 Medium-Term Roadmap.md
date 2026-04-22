# Medium-Term Roadmap — PnL Maximization

## Phase 1: Fix and Deploy (This Week) [IN PROGRESS]
- [x] Fix paper trader signal alignment (v9 deployed)
- [x] Deploy 4H cron (every 4 hours)
- [x] Implement compound returns analysis
- [ ] Update position sizing to 25% risk × 3x (pending Chris approval)
- [ ] Paper trade for 2 weeks
- [ ] Commit all work to git

## Phase 2: Validate (Weeks 2-4)
- [ ] Measure actual PF vs backtest PF over 2 weeks
- [ ] Test dYdX v4 — verify Ontario access, data pipeline, fees
- [ ] Add regime-adaptive sizing — CHOP/TREND detection, momentum filter
- [ ] Connect Jupiter execution pipeline
- [ ] Test LINK as SHORT candidate (detected crossover 2026-04-21)

## Phase 3: Go Live (Week 4+)
- [ ] Paper PF > 1.5 over 2 weeks
- [ ] Execution pipeline tested
- [ ] Position sizing validated at target risk level
- [ ] Risk limits configured
- [ ] Chris approval for first trade
- [ ] Start 1x → scale to 3x after 1 week clean execution

## Phase 4: Expand (Month 2+)
- [ ] Polymarket edge discovery — pull crypto markets (tag_id=21), filter volume >$50K, test if ATR/regime signals predict event outcomes
- [ ] Polymarket trader analysis — reverse-engineer top crypto traders via API (closed-positions, positions, traded endpoints), categorize by tag, find systematic edges
- [ ] Multi-timeframe confirmation — 1H timing within 4H signals
- [ ] Funding rate harvesting — extend SHORT holds when funding favorable
- [ ] Additional pairs — test 5000+ bar candidates (INJ, UNI, POL)
- [ ] Hyperliquid investigation — 50x leverage, 0.025% fees

## Key Metrics to Track
- Paper PF (target: >1.5)
- Compound return vs simple sum
- Walk-forward degradation per pair
- Max drawdown vs backtest estimate
- Execution slippage on Jupiter
