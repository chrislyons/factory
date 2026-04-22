#!/usr/bin/env python3
"""Generate Excalidraw architecture diagrams for IG-88."""
import json, os, uuid

DIAGRAM_DIR = "/Users/nesbitt/dev/factory/agents/ig88/docs/ig88/diagrams"
os.makedirs(DIAGRAM_DIR, exist_ok=True)

# Color palette
BLUE = "#a5d8ff"
GREEN = "#b2f2bb"
ORANGE = "#ffd8a8"
PURPLE = "#d0bfff"
RED = "#ffc9c9"
YELLOW = "#fff3bf"
TEAL = "#c3fae8"
PINK = "#fcc2d7"
GRAY = "#e9ecef"
DARK = "#1e1e1e"
BG_ZONE = "#f8f9fa"

UID_COUNTER = [0]
def uid():
    UID_COUNTER[0] += 1
    return f"e{UID_COUNTER[0]}"

def rect(x, y, w, h, bg=BLUE, label=None, id_=None, color=DARK):
    id_ = id_ or uid()
    r = {
        "type": "rectangle", "id": id_, "x": x, "y": y, "width": w, "height": h,
        "strokeColor": color, "backgroundColor": bg, "fillStyle": "solid",
        "strokeWidth": 2, "roughness": 1, "opacity": 100, "roundness": {"type": 3},
    }
    elems = [r]
    if label:
        tid = uid()
        r["boundElements"] = [{"id": tid, "type": "text"}]
        elems.append({
            "type": "text", "id": tid, "x": x+8, "y": y+8, "width": w-16, "height": h-16,
            "text": label, "fontSize": 18, "fontFamily": 1, "strokeColor": color,
            "textAlign": "center", "verticalAlign": "middle",
            "containerId": id_, "originalText": label, "autoResize": True
        })
    return elems

def arrow(x1, y1, x2, y2, label=None, dashed=False, color=DARK):
    dx, dy = x2-x1, y2-y1
    a = {
        "type": "arrow", "id": uid(), "x": x1, "y": y1, "width": abs(dx), "height": abs(dy),
        "points": [[0,0],[dx,dy]], "endArrowhead": "arrow",
        "strokeColor": color, "strokeWidth": 2, "roughness": 1, "opacity": 100,
    }
    if dashed:
        a["strokeStyle"] = "dashed"
    elems = [a]
    if label:
        tid = uid()
        a["boundElements"] = [{"id": tid, "type": "text"}]
        mx, my = x1+dx//2-30, y1+dy//2-15
        elems.append({
            "type": "text", "id": tid, "x": mx, "y": my, "width": 60, "height": 20,
            "text": label, "fontSize": 14, "fontFamily": 1, "strokeColor": "#868e96",
            "textAlign": "center", "verticalAlign": "middle",
            "containerId": a["id"], "originalText": label, "autoResize": True
        })
    return elems

def text(x, y, t, size=20, color=DARK, bold=False):
    return [{
        "type": "text", "id": uid(), "x": x, "y": y, "width": len(t)*size*0.55, "height": size+4,
        "text": t, "fontSize": size, "fontFamily": 1, "strokeColor": color,
        "originalText": t, "autoResize": True
    }]

def zone(x, y, w, h, label, bg=BG_ZONE):
    id_ = uid()
    z = {
        "type": "rectangle", "id": id_, "x": x, "y": y, "width": w, "height": h,
        "strokeColor": "#adb5bd", "backgroundColor": bg, "fillStyle": "solid",
        "strokeWidth": 1, "roughness": 1, "opacity": 40, "strokeStyle": "dashed",
        "roundness": {"type": 3},
    }
    tid = uid()
    z["boundElements"] = [{"id": tid, "type": "text"}]
    return [z, {
        "type": "text", "id": tid, "x": x+12, "y": y+8, "width": w-24, "height": 22,
        "text": label, "fontSize": 16, "fontFamily": 1, "strokeColor": "#868e96",
        "textAlign": "left", "verticalAlign": "top",
        "containerId": id_, "originalText": label, "autoResize": True
    }]

def save_diagram(path, elements, bg="#ffffff"):
    doc = {
        "type": "excalidraw", "version": 2, "source": "ig88-agent",
        "elements": elements,
        "appState": {"viewBackgroundColor": bg}
    }
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"  Saved: {os.path.basename(path)} ({len(elements)} elements)")

# ============================================================
# DIAGRAM 1: System Architecture Overview
# ============================================================
def diagram_system_arch():
    UID_COUNTER[0] = 0
    e = []

    # Title
    e += text(320, 20, "IG-88 System Architecture", size=28, color=DARK)

    # Data Sources zone
    e += zone(30, 80, 280, 340, "DATA SOURCES (Free)")
    e += rect(50, 120, 240, 50, bg=TEAL, label="Kraken OHLCV API")
    e += rect(50, 185, 240, 50, bg=TEAL, label="CoinGecko Global API")
    e += rect(50, 250, 240, 50, bg=TEAL, label="Fear & Greed Index")
    e += rect(50, 315, 240, 50, bg=TEAL, label="Polymarket Gamma API")
    e += rect(50, 370, 240, 50, bg=TEAL, label="Jupiter Swap API")

    # Processing zone
    e += zone(370, 80, 420, 470, "IG-88 CORE")
    e += rect(390, 120, 180, 60, bg=PURPLE, label="Regime Detection")
    e += rect(590, 120, 180, 60, bg=BLUE, label="4H ATR Scanner")
    e += rect(390, 200, 180, 60, bg=BLUE, label="Bollinger MR")
    e += rect(590, 200, 180, 60, bg=BLUE, label="1H ATR Scanner")
    e += rect(390, 280, 180, 60, bg=ORANGE, label="Paper Trader v9")
    e += rect(590, 280, 180, 60, bg=ORANGE, label="Polymarket Trader")
    e += rect(390, 360, 180, 60, bg=YELLOW, label="Executor Bridge")
    e += rect(590, 360, 180, 60, bg=YELLOW, label="Portfolio Monitor")
    e += rect(490, 440, 180, 60, bg=GREEN, label="Scan Loop (cron)")

    # Venues zone
    e += zone(850, 80, 280, 340, "VENUES")
    e += rect(870, 120, 240, 60, bg=GREEN, label="Kraken Spot\n(36 pairs)")
    e += rect(870, 200, 240, 60, bg=GREEN, label="Jupiter Perps\n(SOL, ETH, BTC)")
    e += rect(870, 280, 240, 60, bg=GREEN, label="Polymarket\n(Prediction Mkts)")

    # Infra zone
    e += zone(370, 560, 420, 120, "INFRASTRUCTURE")
    e += rect(390, 590, 180, 60, bg=PINK, label="OpenRouter LLM\n(Mimo v2 Pro)")
    e += rect(590, 590, 180, 60, bg=PINK, label="Infisical Secrets\n(19 keys)")

    # Arrows: Sources -> Core
    e += arrow(290, 145, 390, 145, "OHLCV")
    e += arrow(290, 210, 390, 225, "")
    e += arrow(290, 275, 390, 305, "")
    e += arrow(290, 340, 590, 310, "markets")
    e += arrow(290, 395, 590, 395, "")

    # Arrows: Core internal
    e += arrow(480, 180, 480, 200, "")
    e += arrow(680, 180, 680, 200, "")
    e += arrow(480, 260, 480, 280, "")
    e += arrow(680, 260, 680, 280, "")
    e += arrow(480, 340, 480, 360, "")
    e += arrow(680, 340, 680, 360, "")
    e += arrow(580, 470, 580, 340, "triggers", dashed=True)

    # Arrows: Core -> Venues
    e += arrow(770, 150, 870, 150, "execute")
    e += arrow(770, 230, 870, 230, "execute")
    e += arrow(770, 310, 870, 310, "execute")

    # Arrows: Infra -> Core
    e += arrow(480, 590, 480, 500, "LLM", dashed=True)
    e += arrow(680, 590, 680, 420, "keys", dashed=True)

    save_diagram(f"{DIAGRAM_DIR}/01_system_architecture.excalidraw", e)

# ============================================================
# DIAGRAM 2: Trading Pipeline Flow
# ============================================================
def diagram_pipeline():
    UID_COUNTER[0] = 0
    e = []
    e += text(250, 20, "Trading Pipeline — Signal to Execution", size=28, color=DARK)

    # Pipeline steps
    steps = [
        (40, 100, "1. OHLCV Fetch", TEAL, "Kraken 1h candles\n11 pairs x 730 bars"),
        (240, 100, "2. Regime Filter", PURPLE, "BTC trend + F&G\n+ mcap + funding"),
        (440, 100, "3. ATR Compute", BLUE, "ATR(14) on 4H\nSMA100 crossover"),
        (640, 100, "4. Signal Gen", ORANGE, "SMA100 cross = entry\nATR x2 = stop"),
    ]
    for x, y, label, bg, desc in steps:
        e += rect(x, y, 180, 70, bg=bg, label=label)
        e += text(x+10, y+75, desc, size=14, color="#868e96")

    steps2 = [
        (40, 260, "5. Risk Check", YELLOW, "Max $500/pos\nMax 8 open"),
        (240, 260, "6. Paper Fill", GREEN, "Simulated entry\nTrack P&L"),
        (440, 260, "7. Position Mon", PINK, "Check stops/targets\n4H candle close"),
        (640, 260, "8. Exit Signal", RED, "Stop hit or\nSMA100 cross down"),
    ]
    for x, y, label, bg, desc in steps2:
        e += rect(x, y, 180, 70, bg=bg, label=label)
        e += text(x+10, y+75, desc, size=14, color="#868e96")

    # Arrows between steps
    e += arrow(220, 135, 240, 135)
    e += arrow(420, 135, 440, 135)
    e += arrow(620, 135, 640, 135)
    e += arrow(730, 170, 730, 260, "", dashed=True)
    e += arrow(220, 295, 240, 295)
    e += arrow(420, 295, 440, 295)
    e += arrow(620, 295, 640, 295)

    # Live execution path
    e += zone(30, 380, 790, 130, "LIVE EXECUTION PATH (when funded)")
    e += rect(50, 410, 180, 70, bg=GREEN, label="Executor Bridge")
    e += rect(270, 410, 180, 70, bg=GREEN, label="Jupiter Ultra API")
    e += rect(490, 410, 180, 70, bg=GREEN, label="TX Sign + Send")
    e += rect(710, 410, 90, 70, bg=GREEN, label="Filled")

    e += arrow(230, 445, 270, 445)
    e += arrow(450, 445, 490, 445)
    e += arrow(670, 445, 710, 445)

    e += arrow(730, 330, 140, 410, "v9 signals", dashed=True)

    # Decision diamond
    e += text(300, 530, "Regime = RISK_ON?  Score >= 4?  Conviction >= 0.6?", size=16, color=DARK)
    e += text(300, 555, "YES -> auto-execute  |  NO -> skip  |  First trade -> Chris approval", size=14, color="#868e96")

    save_diagram(f"{DIAGRAM_DIR}/02_trading_pipeline.excalidraw", e)

# ============================================================
# DIAGRAM 3: Strategy Portfolio + Edge Rankings
# ============================================================
def diagram_strategies():
    UID_COUNTER[0] = 0
    e = []
    e += text(250, 20, "Strategy Portfolio — PnL% Rankings", size=28, color=DARK)

    # Header
    e += rect(40, 70, 850, 40, bg=GRAY, label="Strategy              | Venue       | CAGR     | WR    | PF   | Status")
    e += text(50, 78, "Strategy              | Venue       | CAGR     | WR    | PF   | Status", size=14, color=DARK)

    # Rows
    rows = [
        ("4H ATR + 2x lev", "Kraken Spot", "15-17%", "56%", "1.58", "NEEDS LIVE TEST", ORANGE),
        ("4H ATR conservative", "Kraken Spot", "6.94%", "56%", "1.58", "PAPER TRADING", GREEN),
        ("1H ATR + 2x lev", "Kraken Spot", "6-8%", "54%", "1.42", "SUPPLEMENTARY", BLUE),
        ("Bollinger MR + 2x", "Kraken Spot", "3-6%", "68%", "1.35", "PRE-WALK-FWD", YELLOW),
        ("Polymarket LLM", "Polymarket", "TBD", "TBD", "TBD", "SCANNING", BLUE),
        ("SHORT channel", "ALL", "NEGATIVE", "<50%", "<1.0", "DO NOT TRADE", RED),
    ]
    y = 120
    for strat, venue, cagr, wr, pf, status, bg in rows:
        e += rect(40, y, 850, 40, bg=bg, label="")
        e += text(50, y+10, f"{strat:<22}{venue:<14}{cagr:<11}{wr:<8}{pf:<7}{status}", size=14, color=DARK)
        y += 45

    # Key insight box
    e += zone(40, y+30, 850, 100, "KEY FINDINGS")
    e += text(60, y+60, "1. SHORT channel has NEGATIVE edge on all 29 pairs tested. Never trade SHORT on spot.", size=14, color=DARK)
    e += text(60, y+80, "2. 2x leverage doubles returns with acceptable risk (DD stays <12%). 3x = too risky.", size=14, color=DARK)
    e += text(60, y+100, "3. Regime filter saves 1-2% by skipping chop/risk-off periods.", size=14, color=DARK)
    e += text(60, y+120, "4. Paper trader v9 now uses correct SMA100 signal (v1-v8 had wrong Donchian20).", size=14, color=DARK)

    save_diagram(f"{DIAGRAM_DIR}/03_strategy_portfolio.excalidraw", e)

# ============================================================
# DIAGRAM 4: Venue Architecture
# ============================================================
def diagram_venues():
    UID_COUNTER[0] = 0
    e = []
    e += text(280, 20, "Venue Architecture", size=28, color=DARK)

    # Kraken
    e += zone(30, 80, 340, 350, "KRAKEN SPOT")
    e += rect(50, 115, 300, 50, bg=TEAL, label="OHLCV API (public)")
    e += rect(50, 180, 300, 50, bg=BLUE, label="Trading API (private)")
    e += rect(50, 245, 300, 50, bg=ORANGE, label="Paper Trader v9")
    e += rect(50, 310, 300, 50, bg=GREEN, label="Executor Bridge")
    e += arrow(200, 165, 200, 180)
    e += arrow(200, 230, 200, 245)
    e += arrow(200, 295, 200, 310)
    e += text(50, 370, "36 pairs | 0.26% taker | CAD/USD", size=13, color="#868e96")
    e += text(50, 390, "Ontario: ACCESSIBLE", size=13, color="#2b8a3e")

    # Jupiter
    e += zone(410, 80, 340, 350, "JUPITER (Solana)")
    e += rect(430, 115, 300, 50, bg=TEAL, label="Quote API (public)")
    e += rect(430, 180, 300, 50, bg=BLUE, label="Solana Wallet")
    e += rect(430, 245, 300, 50, bg=ORANGE, label="Perps Engine")
    e += rect(430, 310, 300, 50, bg=GREEN, label="TX Sign + Broadcast")
    e += arrow(580, 165, 580, 180)
    e += arrow(580, 230, 580, 245)
    e += arrow(580, 295, 580, 310)
    e += text(430, 370, "0.08% fees | SOL/ETH/BTC perps", size=13, color="#868e96")
    e += text(430, 390, "Needs: SOL (gas) + USDC", size=13, color="#e67700")

    # Polymarket
    e += zone(410, 460, 340, 210, "POLYMARKET")
    e += rect(430, 495, 300, 50, bg=TEAL, label="Gamma API (public)")
    e += rect(430, 560, 300, 50, bg=PURPLE, label="LLM Probability Engine")
    e += rect(430, 620, 300, 50, bg=GREEN, label="Paper Trader (edge calc)")
    e += arrow(580, 545, 580, 560)
    e += arrow(580, 610, 580, 620)
    e += text(430, 680, "1.56% taker | Binary resolution", size=13, color="#868e96")

    # LunarCrush (crossed out)
    e += zone(30, 460, 340, 210, "LUNARCRUSH (BLOCKED)")
    e += rect(50, 495, 300, 80, bg=RED, label="API v4: 402\nSubscription required\nFree tier = no access")
    e += text(50, 590, "NOT IN USE — upgrade $199/mo required", size=13, color="#c92a2a")
    e += text(50, 615, "Sentiment edge not worth cost", size=13, color="#868e96")

    save_diagram(f"{DIAGRAM_DIR}/04_venue_architecture.excalidraw", e)

# ============================================================
# DIAGRAM 5: Data Flow & Scan Cycle
# ============================================================
def diagram_scan_cycle():
    UID_COUNTER[0] = 0
    e = []
    e += text(280, 20, "Autonomous Scan Cycle", size=28, color=DARK)

    # Center circle concept — flow instead
    steps = [
        (350, 80, "scan-loop.py\n(cron)", PURPLE),
        (350, 180, "Regime Check\n(BTC+F&G+mcap)", ORANGE),
        (180, 280, "4H ATR Scan\n11 pairs", BLUE),
        (520, 280, "Polymarket\nScan 50 mkts", BLUE),
        (180, 400, "Signal Filter\n(score>=4)", YELLOW),
        (520, 400, "Edge Calc\n(|LLM-market|)", YELLOW),
        (180, 520, "Paper Fill\nv9 trader", GREEN),
        (520, 520, "Paper Fill\nPM trader", GREEN),
        (350, 620, "Portfolio Report\n→ Matrix", PINK),
    ]
    for i, (x, y, label, bg) in enumerate(steps):
        e += rect(x, y, 160, 70, bg=bg, label=label)

    # Arrows
    e += arrow(430, 150, 430, 180)
    e += arrow(430, 250, 260, 280)
    e += arrow(430, 250, 600, 280)
    e += arrow(260, 350, 260, 400)
    e += arrow(600, 350, 600, 400)
    e += arrow(260, 470, 260, 520)
    e += arrow(600, 470, 600, 520)
    e += arrow(260, 590, 430, 620)
    e += arrow(600, 590, 430, 620)

    # Timer feedback
    e += arrow(260, 690, 260, 710, "", dashed=True)
    e += text(220, 720, "Next scan in 4h", size=14, color="#868e96")
    e += arrow(260, 710, 260, 70, "", dashed=True)
    e += arrow(260, 70, 430, 115, "", dashed=True)

    save_diagram(f"{DIAGRAM_DIR}/05_scan_cycle.excalidraw", e)

# ============================================================
# DIAGRAM 6: Project Structure
# ============================================================
def diagram_project_structure():
    UID_COUNTER[0] = 0
    e = []
    e += text(280, 20, "Project File Structure", size=28, color=DARK)

    tree = [
        ("agents/ig88/", 40, 80, GRAY),
        ("  src/", 70, 120, BLUE),
        ("    quant/ (9 modules)", 100, 150, TEAL),
        ("    trading/ (10 modules)", 100, 185, TEAL),
        ("    scanner/ (5 modules)", 100, 220, TEAL),
        ("    viz/ (10 modules)", 100, 255, TEAL),
        ("  scripts/ (18 production)", 70, 300, BLUE),
        ("    atr4h_paper_trader_v9.py", 100, 330, GREEN),
        ("    executor.py", 100, 365, GREEN),
        ("    scan-loop.py", 100, 400, GREEN),
        ("    portfolio.py", 100, 435, GREEN),
        ("    archive/ (240+ files)", 100, 475, GRAY),
        ("  config/", 70, 520, ORANGE),
        ("    trading.yaml (36 pairs)", 100, 550, YELLOW),
        ("  docs/ig88/ (IG88081-086)", 70, 590, PURPLE),
        ("  memory/ig88/", 70, 625, PINK),
        ("    scratchpad.md", 100, 655, PINK),
        ("    fact/trading.md", 100, 685, PINK),
        ("    fact/infrastructure.md", 100, 715, PINK),
    ]
    for label, x, y, bg in tree:
        w = max(len(label) * 10 + 20, 200)
        e += rect(x, y, w, 28, bg=bg, label=label)

    save_diagram(f"{DIAGRAM_DIR}/06_project_structure.excalidraw", e)

# ============================================================
# GENERATE ALL
# ============================================================
print("Generating IG-88 architecture diagrams...")
diagram_system_arch()
diagram_pipeline()
diagram_strategies()
diagram_venues()
diagram_scan_cycle()
diagram_project_structure()
print(f"\nDone. {len(os.listdir(DIAGRAM_DIR))} diagrams in {DIAGRAM_DIR}")
