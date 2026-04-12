# IG88025 Live Execution Pipeline & Graduation Framework

## Status
- **Pipeline Status**: VALIDATED
- **Venue**: Kraken Spot (ZCAD Funded)
- **Mode**: Shadow Monitoring (Accumulating signals)
- **Date**: 2026-04-11

## 1. Architecture Overview
The execution pipeline has transitioned from theoretical backtesting to a hardened live-ready state.

### Execution Flow
`h3_scanner.py` $\rightarrow$ `KrakenExecutor` $\rightarrow$ `Kraken API` $\rightarrow$ `Order Polling` $\rightarrow$ `Memory Log`

### Components
- **`h3_scanner.py`**: Expanded to multi-asset parallel scanning (SOL, BTC, ETH, LINK, AVAX, NEAR). Gated by BTC Trend Regime.
- **`kraken_executor.py`**: The safety layer. Enforces risk limits and manages the order lifecycle.
- **`shadow_test.py`**: Validation harness for round-trip execution (Buy $\rightarrow$ Fill $\rightarrow$ Sell $\rightarrow$ Fill).

## 2. Risk Guardrails
The following limits are hard-coded into `src/trading/kraken_executor.py` and cannot be bypassed by the scanner:
- **Max Position Size**: $50.00 USD/CAD
- **Daily Loss Limit**: $25.00 USD/CAD
- **Max Concurrent Positions**: 1
- **Slippage Budget**: 130.5 bps (Breaking point for PF 2.0)

## 3. Validation History (Shadow Tests)
A series of round-trip tests were conducted on 2026-04-11 to iron out API quirks:
- **Bug FIX-A**: Corrected `txid` parsing. API returned `txid` as lists (e.g., `['TXID']`); executor now strictly casts to string.
- **Bug FIX-B**: Handled `EOrder:Invalid order` errors. Added a 2s retry loop to account for Kraken's internal indexing latency.
- **Bug FIX-C**: Aligned currency pairs. Transitioned from `SOLUSD` to `SOLCAD` to match account funding (ZCAD).

**Result**: Successful round-trip verified. Order $\rightarrow$ Confirmation $\rightarrow$ Log cycle is operational.

## 4. Graduation Criteria (Accelerated)
To transition from `live_mode=False` to `live_mode=True`, the following must be met:
1. **30 Valid Signal Detections**: Across any of the 6 assets, matching H3 characteristics.
2. **Pipeline Validation**: 
   - Entry price must be within 0.5% of candle close.
   - Regime filters must evaluate correctly in real-time.
   - ATR stops must be placed at correct levels.
3. **Shadow Execution**: (Completed) Round-trip SOLCAD test successful.

## 5. Next Steps
- Monitor 4h candles for signal accumulation.
- Begin research on **Indicator Primitive Framework** to replace hand-coded strategies with systematic compositions.
