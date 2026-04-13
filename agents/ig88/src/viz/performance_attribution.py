"""
Performance Attribution Scene — 25/75 layout with 2x2 grid.
Shows PnL by pair, PnL by regime, PnL by day of week, WR by tier.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
import json
from datetime import datetime
from collections import defaultdict
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE, REGIME_COLORS,
    header_text, mono_text, styled_text,
)

SZ_TITLE = 22
SZ_SECTION = 14
SZ_LABEL = 12
SZ_VALUE = 14
SZ_SMALL = 10


def load_paper_trades():
    """Load paper trades from jsonl file."""
    trades = []
    try:
        with open('/Users/nesbitt/dev/factory/agents/ig88/data/paper_trades.jsonl', 'r') as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        return trades
    except Exception as e:
        print(f"Error loading paper trades: {e}")
        return []


def generate_synthetic_trades(n_trades=50):
    """Generate synthetic trades for demo."""
    rng = np.random.default_rng(42)
    
    pairs = ['SOL-PERP', 'AVAX-PERP', 'ETH-PERP', 'NEAR-PERP', 'LINK-PERP', 'BTC-PERP']
    regimes = ['RISK_ON', 'NEUTRAL', 'RISK_OFF']
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    trades = []
    base_time = datetime(2026, 4, 1)
    
    for i in range(n_trades):
        pair = rng.choice(pairs)
        regime = rng.choice(regimes, p=[0.6, 0.3, 0.1])
        day = rng.choice(days)
        
        # Generate PnL
        is_win = rng.random() < 0.58
        if is_win:
            pnl_pct = rng.uniform(1.0, 8.0)
        else:
            pnl_pct = -rng.uniform(1.0, 5.0)
        
        # Tier based on pnl magnitude
        abs_pnl = abs(pnl_pct)
        if abs_pnl < 2:
            tier = 'SCALP'
        elif abs_pnl < 4:
            tier = 'SWING'
        else:
            tier = 'TREND'
        
        trade = {
            'pair': pair,
            'regime_state': regime,
            'pnl_pct': pnl_pct,
            'outcome': 'win' if is_win else 'loss',
            'entry_timestamp': (base_time + np.timedelta64(i * 8, 'h')).isoformat(),
            'tier': tier,
            'day_of_week': day,
        }
        trades.append(trade)
    
    return trades


def compute_attribution(trades):
    """Compute performance attribution by different dimensions."""
    if not trades:
        return None
    
    # By pair
    by_pair = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0})
    for t in trades:
        pair = t.get('pair', 'UNKNOWN')
        pnl = t.get('pnl_pct') or 0  # Handle None values
        by_pair[pair]['pnl'] += pnl
        by_pair[pair]['count'] += 1
        if pnl > 0:
            by_pair[pair]['wins'] += 1
    
    # By regime
    by_regime = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0})
    for t in trades:
        regime = t.get('regime_state') or 'UNKNOWN'
        pnl = t.get('pnl_pct') or 0
        by_regime[regime]['pnl'] += pnl
        by_regime[regime]['count'] += 1
        if pnl > 0:
            by_regime[regime]['wins'] += 1
    
    # By day of week
    by_day = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0})
    for t in trades:
        # Extract day from timestamp or use stored day
        ts = t.get('entry_timestamp', '')
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                day = dt.strftime('%a')
            except:
                day = t.get('day_of_week', 'Unknown')
        else:
            day = t.get('day_of_week', 'Unknown')
        
        pnl = t.get('pnl_pct') or 0
        by_day[day]['pnl'] += pnl
        by_day[day]['count'] += 1
        if pnl > 0:
            by_day[day]['wins'] += 1
    
    # By tier (based on PnL magnitude)
    by_tier = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0})
    for t in trades:
        pnl = t.get('pnl_pct') or 0
        abs_pnl = abs(pnl)
        
        if abs_pnl < 2:
            tier = 'SCALP'
        elif abs_pnl < 4:
            tier = 'SWING'
        else:
            tier = 'TREND'
        
        by_tier[tier]['pnl'] += pnl
        by_tier[tier]['count'] += 1
        if pnl > 0:
            by_tier[tier]['wins'] += 1
    
    return {
        'by_pair': dict(by_pair),
        'by_regime': dict(by_regime),
        'by_day': dict(by_day),
        'by_tier': dict(by_tier),
        'total_pnl': sum(t.get('pnl_pct') or 0 for t in trades),
        'total_trades': len(trades),
    }


def draw_bar_chart(data_dict, title, ax, is_pnl=True):
    """Draw a bar chart on the given axes."""
    if not data_dict:
        return
    
    items = sorted(data_dict.items(), key=lambda x: x[1]['pnl'], reverse=True)
    
    n_items = len(items)
    bar_width = 0.6 / max(n_items, 1)
    
    max_abs_val = max(abs(v['pnl']) for _, v in items) if items else 1
    
    for i, (key, val) in enumerate(items):
        pnl = val['pnl']
        count = val['count']
        wins = val['wins']
        
        # Bar height (normalized)
        height = abs(pnl) / max_abs_val * 2.5 if max_abs_val > 0 else 0
        
        # Color based on PnL
        color = MANIM_GREEN if pnl >= 0 else MANIM_RED
        
        # Draw bar
        x = -1.5 + i * (3.0 / n_items)
        bar = Rectangle(
            width=bar_width,
            height=max(height, 0.05),
            fill_color=color,
            fill_opacity=0.8,
            stroke_color=color,
            stroke_width=1,
        )
        bar.move_to(ax.c2p(x, height / 2 if pnl >= 0 else -height / 2))
        
        # Label
        label_text = styled_text(key[:4], size=8, color=MANIM_GREY, font=FONT_SANS
        ).next_to(bar, DOWN, buff=0.05)
        
        # Value
        value_text = mono_text(f"{pnl:+.1f}", size=8, color=color
        ).next_to(bar, UP, buff=0.05)
        
        ax.add(bar, label_text, value_text)


class PerformanceAttributionScene(Scene):
    def construct(self):
        """
        Render performance attribution in 2x2 grid.
        """
        self.camera.background_color = "#09090b"
        
        # Load trades
        trades = load_paper_trades()
        if not trades or len(trades) < 5:
            trades = generate_synthetic_trades(40)
        
        # Compute attribution
        attr = compute_attribution(trades)
        
        # === TITLE ===
        title = header_text("PERFORMANCE ATTRIBUTION", size=SZ_TITLE).to_edge(UP, buff=0.15)
        self.add(title)
        
        # Summary stats
        total_pnl = attr['total_pnl']
        total_trades = attr['total_trades']
        total_pnl_color = MANIM_GREEN if total_pnl >= 0 else MANIM_RED
        
        summary_text = VGroup(
            mono_text(f"Total PnL: {total_pnl:+.2f}%", size=SZ_SMALL, color=total_pnl_color, weight="BOLD"),
            styled_text("·", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{total_trades} trades", size=SZ_SMALL, color=MANIM_WHITE),
        ).arrange(RIGHT, buff=0.2).next_to(title, DOWN, buff=0.1)
        self.add(summary_text)
        
        # === 2x2 GRID ===
        grid_positions = [
            (LEFT * 2.5 + UP * 1.0),   # Top-left
            (RIGHT * 1.5 + UP * 1.0),  # Top-right
            (LEFT * 2.5 + DOWN * 1.5), # Bottom-left
            (RIGHT * 1.5 + DOWN * 1.5),# Bottom-right
        ]
        
        charts = [
            ("PNL BY PAIR", attr['by_pair']),
            ("PNL BY REGIME", attr['by_regime']),
            ("PNL BY DAY", attr['by_day']),
            ("WIN RATE BY TIER", attr['by_tier']),
        ]
        
        for idx, (chart_title, chart_data) in enumerate(charts):
            pos = grid_positions[idx]
            
            # Chart title
            chart_title_text = styled_text(chart_title, size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
            ).move_to(pos + UP * 1.5)
            self.add(chart_title_text)
            
            # Chart area
            chart_area = Rectangle(
                width=3.5,
                height=2.5,
                stroke_color=MANIM_GREY,
                stroke_opacity=0.3,
                fill_opacity=0,
            ).move_to(pos)
            self.add(chart_area)
            
            # Draw bars
            if chart_data:
                items = sorted(chart_data.items(), key=lambda x: x[1]['pnl'], reverse=True)
                n_items = len(items)
                
                if n_items > 0:
                    max_abs_val = max(abs(v['pnl']) for _, v in items)
                    
                    for i, (key, val) in enumerate(items):
                        pnl = val['pnl']
                        count = val['count']
                        wins = val['wins']
                        
                        # Calculate win rate if this is win rate chart
                        if "WIN RATE" in chart_title:
                            wr = (wins / count * 100) if count > 0 else 0
                            value = wr
                            max_val = 100
                            color = MANIM_GREEN if wr >= 50 else MANIM_RED
                        else:
                            value = pnl
                            max_val = max_abs_val
                            color = MANIM_GREEN if pnl >= 0 else MANIM_RED
                        
                        # Bar dimensions
                        bar_width = min(0.4, 2.5 / n_items)
                        bar_height = abs(value) / max_val * 1.8 if max_val > 0 else 0.05
                        
                        # Position
                        x_offset = (i - (n_items - 1) / 2) * (2.5 / n_items)
                        y_offset = bar_height / 2 if value >= 0 else -bar_height / 2
                        
                        bar = Rectangle(
                            width=bar_width,
                            height=bar_height,
                            fill_color=color,
                            fill_opacity=0.8,
                            stroke_color=color,
                            stroke_width=0.5,
                        ).move_to(pos + RIGHT * x_offset + UP * y_offset)
                        
                        # Key label
                        key_label = styled_text(key[:5], size=8, color=MANIM_GREY, font=FONT_SANS
                        ).next_to(bar, DOWN, buff=0.05)
                        
                        # Value label
                        if "WIN RATE" in chart_title:
                            val_label = mono_text(f"{value:.0f}%", size=8, color=color)
                        else:
                            val_label = mono_text(f"{value:+.1f}", size=8, color=color)
                        val_label.next_to(bar, UP, buff=0.05)
                        
                        self.add(bar, key_label, val_label)
            
            # Zero line for PnL charts
            if "WIN RATE" not in chart_title:
                zero_line = Line(
                    chart_area.get_left() + UP * 1.25,
                    chart_area.get_right() + UP * 1.25,
                    color=MANIM_GREY,
                    stroke_opacity=0.5,
                )
                self.add(zero_line)
        
        # Footer
        footer = styled_text("IG-88 · Performance Attribution · Paper Trading", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).to_edge(DOWN, buff=0.1)
        self.add(footer)
        
        self.wait(1)
