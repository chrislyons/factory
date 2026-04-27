# ETH Short Edge Max Hold Test Results
## Date: 2026-04-15
## Data: ETH/USDT daily candles from Jan 2020 to Apr 2026 (2,297 bars)

### Test Parameters
- Max hold values tested: 5, 7, 10, 15, 20, 30, 45 bars
- Trail stop: 2.0x ATR
- Friction: 0.001 (Jupiter)
- Funding rate: 0.0003/day (0.0001 per 8h)

---

## EMA50 Short Results

| max_hold | PF    | Win%  | Avg Ret | Total Ret | Max DD    | Dim%  | Net Avg | Net Total | Trades |
|----------|-------|-------|---------|-----------|-----------|-------|---------|-----------|--------|
| 5        | 0.985 | 47.1% | -0.05%  | -1.54%    | 64.11%    | 7.4%  | -0.19%  | -6.61%    | 34     |
| 7        | 0.837 | 47.1% | -0.63%  | -21.58%   | 68.45%    | 10.1% | -0.84%  | -28.51%   | 34     |
| 10       | 1.160 | 45.2% | 0.56%   | 17.32%    | 39.04%    | 12.2% | 0.29%   | 8.89%     | 31     |
| 15       | 0.729 | 37.9% | -1.45%  | -42.16%   | 100.73%   | 15.3% | -1.82%  | -52.72%   | 29     |
| 20       | 0.935 | 39.3% | -0.28%  | -7.98%    | 70.50%    | 18.4% | -0.74%  | -20.67%   | 28     |
| 30       | 1.369 | 39.3% | 1.73%   | 48.48%    | 69.71%    | 22.9% | 1.17%   | 32.73%    | 28     |
| 45       | 1.553 | 39.3% | 2.58%   | 72.20%    | 68.91%    | 26.7% | 1.92%   | 53.81%    | 28     |

## 20-Low Short Results

| max_hold | PF    | Win%  | Avg Ret | Total Ret | Max DD    | Dim%  | Net Avg | Net Total | Trades |
|----------|-------|-------|---------|-----------|-----------|-------|---------|-----------|--------|
| 5        | 1.266 | 48.6% | 0.97%   | 34.09%    | 66.43%    | 7.5%  | 0.83%   | 28.93%    | 35     |
| 7        | 0.879 | 41.2% | -0.62%  | -20.92%   | 88.30%    | 10.1% | -0.82%  | -27.85%   | 34     |
| 10       | 1.378 | 45.5% | 1.40%   | 46.32%    | 56.04%    | 13.6% | 1.12%   | 36.93%    | 33     |
| 15       | 1.010 | 38.7% | 0.06%   | 1.79%     | 75.71%    | 17.9% | -0.34%  | -10.54%   | 31     |
| 20       | 1.803 | 46.4% | 3.48%   | 97.46%    | 58.74%    | 20.0% | 2.99%   | 83.69%    | 28     |
| 30       | 1.348 | 46.2% | 1.70%   | 44.24%    | 50.69%    | 23.6% | 1.08%   | 27.98%    | 26     |
| 45       | 1.105 | 38.5% | 0.59%   | 15.39%    | 60.79%    | 24.3% | -0.05%  | -1.38%    | 26     |

---

## Key Findings

### EMA50 Short
- **Optimal max_hold: 45 bars** (PF 1.55, Net Return 53.81%)
- Shorter holds (5-20 bars) produce negative net returns due to funding drag
- max_hold=10 is the only shorter option with positive net return (8.89%)
- Win rate decreases with longer holds (47% → 39%) but avg return per trade increases

### 20-Low Short  
- **Optimal max_hold: 20 bars** (PF 1.80, Net Return 83.69%)
- max_hold=5 also performs well (PF 1.27, Net Return 28.93%)
- max_hold=10 is solid (PF 1.38, Net Return 36.93%)
- Longer holds (30-45) see significant funding cost erosion

### Funding Cost Impact
- 5 bars: ~5% funding cost
- 10 bars: ~9% funding cost  
- 20 bars: ~13-14% funding cost
- 30 bars: ~16% funding cost
- 45 bars: ~17-18% funding cost

### Recommendation
For EMA50 Short: Keep max_hold=30 or 45 bars (funding drag kills shorter holds)
For 20-Low Short: Consider max_hold=20 bars (best PF and net return) or max_hold=10 for lower market exposure
