# IG-88 Scripts

## Active Scripts (Production)

| Script | Purpose | Called By |
|--------|---------|-----------|
| `scan-loop.py` | Main autonomous scan loop (regime + venues + Polymarket) | Hermes/cron |
| `mr_scan_final.py` | MR signal scanner with dedup + current prices | Cron (every 4h) |
| `paper_trade_runner.py` | Paper trade execution and state management | mr_scan_final.py |
| `fetch_ohlcv.py` | Fetch historical OHLCV data from Binance | Manual/one-off |
| `check_data_freshness.py` | Verify parquet data is up-to-date | Manual |
| `paper_status.py` | Print current paper trading status | Manual |
| `render_paper_status.py` | Render paper status as visual | Manual |
| `generate_manifest.py` | Generate data manifest | Manual |
| `run_scanner.sh` | Shell wrapper for mr_scan_final.py | Cron |

## Infrastructure Scripts

| Script | Purpose |
|--------|---------|
| `deploy-to-rp5.sh` | Deploy to RP5 (legacy) |
| `install-bridge.sh` | Install Matrix bridge |
| `install-services.sh` | Install systemd services |
| `security-audit.sh` | Run security audit |
| `test-matrix.sh` | Test Matrix connectivity |
| `run-cycle.sh` | Run full cycle (legacy) |

## Archived Scripts

197 one-off test scripts moved to `archive/` on 2026-04-14 during IG88049 system review.
These include strategy tests, optimization scripts, debug scripts, and backtest experiments.
They are preserved for reference but are NOT active code.
