"""
Regime Detection Scene — 25/75 layout.
Shows ATR percentage vs 20-day average per pair, classifying regimes.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE, MANIM_PURPLE, REGIME_COLORS,
    header_text, mono_text, styled_text,
)
from viz.data_loader import load_ohlcv

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12

# 12 pairs from friction_tracker.py
PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']

# Regime classification thresholds
REGIME_THRESHOLDS = {
    'LOW_VOL': (0, 2.0),      # ATR% < 2%
    'NORMAL': (2.0, 4.0),     # ATR% 2-4%
    'HIGH_VOL': (4.0, 999),   # ATR% > 4%
}

# Regime colors
REGIME_VIS_COLORS = {
    'LOW_VOL': '#3b82f6',     # Blue
    'NORMAL': '#f59e0b',      # Yellow
    'HIGH_VOL': '#ef4444',    # Red
    'TRENDING': '#a855f7',    # Purple
}


def compute_atr(high, low, close, period=14):
    """Compute Average True Range from OHLCV data."""
    high = np.array(high)
    low = np.array(low)
    close = np.array(close)
    
    # True Range
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    
    # ATR as simple moving average
    atr = np.convolve(tr, np.ones(period)/period, mode='valid')
    
    # ATR percentage (ATR / close price * 100)
    atr_pct = atr / close[period:] * 100
    
    return atr, atr_pct


def compute_adx(high, low, close, period=14):
    """Compute Average Directional Index."""
    high = np.array(high)
    low = np.array(low)
    close = np.array(close)
    n = len(close)
    
    if n < period * 2:
        return np.array([20.0])  # Default value
    
    # Directional movement
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    # True Range
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    
    # Smoothed values
    atr = np.convolve(tr, np.ones(period)/period, mode='valid')
    plus_di = 100 * np.convolve(plus_dm, np.ones(period)/period, mode='valid') / atr
    minus_di = 100 * np.convolve(minus_dm, np.ones(period)/period, mode='valid') / atr
    
    # DX and ADX
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = np.convolve(dx, np.ones(period)/period, mode='valid')
    
    return adx


def load_pair_data(pair, timeframe="240m", exchange="binance"):
    """Load and compute ATR for a single pair."""
    data = load_ohlcv(pair, timeframe, exchange)
    if data is None:
        # Generate synthetic data
        n_bars = 200
        rng = np.random.default_rng(hash(pair) % 10000)
        base_price = 100 + rng.random() * 50
        close = base_price + np.cumsum(rng.standard_normal(n_bars) * 2)
        high = close + np.abs(rng.standard_normal(n_bars) * 1.5)
        low = close - np.abs(rng.standard_normal(n_bars) * 1.5)
        open_ = close + rng.standard_normal(n_bars) * 0.5
        volume = np.abs(rng.standard_normal(n_bars) * 10000) + 5000
        data = {
            'times': np.arange(n_bars),
            'open': open_,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        }
    
    atr, atr_pct = compute_atr(data['high'], data['low'], data['close'])
    adx = compute_adx(data['high'], data['low'], data['close'])
    
    return {
        'atr': atr,
        'atr_pct': atr_pct,
        'adx': adx[-1] if len(adx) > 0 else 20.0,
        'close': data['close'],
        'times': data['times'],
    }


def classify_regime(atr_pct_current, atr_pct_avg, adx):
    """Classify market regime based on ATR and ADX."""
    if adx > 25:
        return 'TRENDING'
    elif atr_pct_current < 2.0:
        return 'LOW_VOL'
    elif atr_pct_current < 4.0:
        return 'NORMAL'
    else:
        return 'HIGH_VOL'


class RegimeDetectionScene(Scene):
    def construct(self):
        """
        Render regime detection visualization.
        Left: Regime stats table for each pair.
        Right: ATR time series with colored bands for top pair.
        """
        self.camera.background_color = "#09090b"
        
        # Load data for all pairs
        pair_data = {}
        for pair in PAIRS:
            pair_data[pair] = load_pair_data(pair)
        
        # Compute current regime for each pair
        regime_stats = []
        for pair in PAIRS:
            data = pair_data[pair]
            if len(data['atr_pct']) > 0:
                current_atr = data['atr_pct'][-1]
                avg_atr = np.mean(data['atr_pct'][-20:]) if len(data['atr_pct']) >= 20 else np.mean(data['atr_pct'])
                adx = data['adx']
                regime = classify_regime(current_atr, avg_atr, adx)
                regime_stats.append({
                    'pair': pair,
                    'atr_pct': current_atr,
                    'atr_avg': avg_atr,
                    'adx': adx,
                    'regime': regime,
                })
            else:
                regime_stats.append({
                    'pair': pair,
                    'atr_pct': 0,
                    'atr_avg': 0,
                    'adx': 20,
                    'regime': 'LOW_VOL',
                })
        
        # Sort by ATR percentage (highest volatility first)
        regime_stats.sort(key=lambda x: x['atr_pct'], reverse=True)
        
        # Select top pair for detailed view
        top_pair = regime_stats[0]['pair']
        top_data = pair_data[top_pair]
        
        # === TITLE ===
        title = header_text("REGIME DETECTION", size=SZ_TITLE).to_edge(UP, buff=0.15)
        self.add(title)
        
        # === LEFT COLUMN: Stats Table ===
        stats_title = styled_text("REGIME STATUS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.6)
        
        # Column headers
        headers = VGroup(
            styled_text("PAIR", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            styled_text("ATR%", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            styled_text("ADX", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            styled_text("REGIME", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
        ).arrange(RIGHT, buff=0.3).next_to(stats_title, DOWN, buff=0.15)
        headers[0].align_to(stats_title, LEFT)
        
        self.add(stats_title, headers)
        
        # Stats rows
        for i, stat in enumerate(regime_stats):
            row_y = headers.get_bottom()[1] - 0.3 - i * 0.35
            
            # Pair name
            pair_text = mono_text(stat['pair'], size=SZ_SMALL, color=MANIM_WHITE)
            pair_text.move_to(LEFT * 2.5 + UP * row_y)
            
            # ATR%
            atr_color = REGIME_VIS_COLORS.get(stat['regime'], MANIM_GREY)
            atr_text = mono_text(f"{stat['atr_pct']:.2f}%", size=SZ_SMALL, color=atr_color, weight="BOLD")
            atr_text.move_to(LEFT * 1.5 + UP * row_y)
            
            # ADX
            adx_color = MANIM_PURPLE if stat['adx'] > 25 else MANIM_GREY
            adx_text = mono_text(f"{stat['adx']:.1f}", size=SZ_SMALL, color=adx_color)
            adx_text.move_to(LEFT * 0.5 + UP * row_y)
            
            # Regime
            regime_color = REGIME_VIS_COLORS.get(stat['regime'], MANIM_GREY)
            regime_text = mono_text(stat['regime'], size=SZ_SMALL, color=regime_color, weight="BOLD")
            regime_text.move_to(RIGHT * 0.5 + UP * row_y)
            
            self.add(pair_text, atr_text, adx_text, regime_text)
        
        # Thin divider line
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)
        self.add(divider)
        
        # === RIGHT COLUMN: ATR Time Series ===
        chart_title = styled_text(f"ATR% — {top_pair}", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).shift(RIGHT * 1.0 + UP * 2.2)
        self.add(chart_title)
        
        atr_pct = top_data['atr_pct']
        if len(atr_pct) > 0:
            n_points = min(len(atr_pct), 100)  # Show last 100 bars
            atr_plot = atr_pct[-n_points:]
            
            # Compute moving average
            ma_period = 20
            ma = np.convolve(atr_plot, np.ones(ma_period)/ma_period, mode='valid')
            ma_x = np.arange(ma_period - 1, n_points)
            
            # Y-axis range
            y_min = max(0, min(atr_plot) * 0.8)
            y_max = max(atr_plot) * 1.2
            
            axes = Axes(
                x_range=[0, n_points - 1, max(1, (n_points - 1) // 5)],
                y_range=[y_min, y_max, (y_max - y_min) / 5],
                x_length=8.0,
                y_length=4.0,
                axis_config={"include_tip": False, "font_size": 14},
            ).shift(RIGHT * 0.8 + DOWN * 0.3)
            
            # X-axis label
            x_label = styled_text("Bars (4h)", size=SZ_LABEL, font=FONT_SANS).next_to(axes.x_axis, DOWN, buff=0.1)
            # Y-axis label
            y_label = styled_text("ATR %", size=SZ_LABEL, font=FONT_SANS).next_to(axes.y_axis, LEFT, buff=0.1).rotate(90 * DEGREES)
            
            self.add(axes, x_label, y_label)
            
            # Regime bands
            band_width = axes.x_length / n_points
            
            # LOW_VOL band (0-2%)
            low_band = Rectangle(
                width=axes.x_length,
                height=axes.y_length * (2.0 - y_min) / (y_max - y_min),
                fill_color=REGIME_VIS_COLORS['LOW_VOL'],
                fill_opacity=0.1,
                stroke_width=0,
            ).move_to(axes.c2p(n_points/2, (2.0 + y_min) / 2))
            self.add(low_band)
            
            # NORMAL band (2-4%)
            normal_band = Rectangle(
                width=axes.x_length,
                height=axes.y_length * (4.0 - 2.0) / (y_max - y_min),
                fill_color=REGIME_VIS_COLORS['NORMAL'],
                fill_opacity=0.1,
                stroke_width=0,
            ).move_to(axes.c2p(n_points/2, 3.0))
            self.add(normal_band)
            
            # Threshold lines
            for threshold, label in [(2.0, "2%"), (4.0, "4%")]:
                if y_min <= threshold <= y_max:
                    line = DashedLine(
                        axes.c2p(0, threshold),
                        axes.c2p(n_points - 1, threshold),
                        color=MANIM_GREY,
                        stroke_opacity=0.5,
                    )
                    label_text = mono_text(label, size=10, color=MANIM_GREY
                    ).next_to(line, RIGHT, buff=0.05)
                    self.add(line, label_text)
            
            # ATR line
            points = [axes.c2p(i, atr_plot[i]) for i in range(n_points)]
            atr_line = VMobject(color=MANIM_BLUE, stroke_width=2)
            atr_line.set_points_smoothly(points)
            self.add(atr_line)
            
            # Moving average line
            ma_points = [axes.c2p(ma_x[i], ma[i]) for i in range(len(ma))]
            ma_line = VMobject(color=MANIM_YELLOW, stroke_width=1.5)
            ma_line.set_points_smoothly(ma_points)
            self.add(ma_line)
            
            # Current value marker
            current_val = atr_plot[-1]
            current_regime = classify_regime(current_val, np.mean(atr_plot[-20:]), top_data['adx'])
            current_color = REGIME_VIS_COLORS.get(current_regime, MANIM_GREY)
            current_dot = Dot(axes.c2p(n_points - 1, current_val), radius=0.06, color=current_color)
            current_label = mono_text(f"{current_val:.2f}%", size=SZ_SMALL, color=current_color, weight="BOLD"
            ).next_to(current_dot, RIGHT, buff=0.1)
            self.add(current_dot, current_label)
            
            # Legend
            legend_items = [
                (MANIM_BLUE, "ATR%"),
                (MANIM_YELLOW, "20-bar MA"),
            ]
            for i, (color, label) in enumerate(legend_items):
                legend_dot = Dot(color=color, radius=0.04).move_to(RIGHT * 4.0 + UP * (1.2 - i * 0.25))
                legend_text = styled_text(label, size=10, color=MANIM_GREY, font=FONT_SANS
                ).next_to(legend_dot, RIGHT, buff=0.1)
                self.add(legend_dot, legend_text)
        
        # Footer
        footer = styled_text("IG-88 · Regime Detection · ATR + ADX", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).to_edge(DOWN, buff=0.1)
        self.add(footer)
        
        self.wait(1)
