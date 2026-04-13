"""
Ichimoku Cloud — 25/75 layout, left-aligned left column.
Loads real OHLCV data when available.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE, MANIM_PURPLE,
    header_text, mono_text, styled_text,
)
from viz.data_loader import load_ohlcv, generate_synthetic_prices

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12


def compute_ichi(prices, tenkan_period=9, kijun_period=26, span_b_period=52):
    """Compute Ichimoku indicators from price array."""
    n = len(prices)
    tenkan = np.full(n, np.nan)
    kijun = np.full(n, np.nan)
    span_a = np.full(n, np.nan)
    span_b = np.full(n, np.nan)
    
    for i in range(tenkan_period, n):
        tenkan[i] = (np.max(prices[i-tenkan_period:i+1]) + np.min(prices[i-tenkan_period:i+1])) / 2
    
    for i in range(kijun_period, n):
        kijun[i] = (np.max(prices[i-kijun_period:i+1]) + np.min(prices[i-kijun_period:i+1])) / 2
    
    for i in range(kijun_period, n):
        if not np.isnan(tenkan[i]) and not np.isnan(kijun[i]):
            span_a[i] = (tenkan[i] + kijun[i]) / 2
    
    for i in range(span_b_period, n):
        span_b[i] = (np.max(prices[i-span_b_period:i+1]) + np.min(prices[i-span_b_period:i+1])) / 2
    
    return tenkan, kijun, span_a, span_b


def compute_ichi_score(prices, idx, rsi_period=14, rsi_threshold=55):
    """Compute Ichimoku score at a specific index."""
    tenkan, kijun, span_a, span_b = compute_ichi(prices)
    
    if idx >= len(prices) or np.isnan(tenkan[idx]) or np.isnan(kijun[idx]):
        return 0, []
    
    score = 0
    signals = []
    
    # 1. Tenkan > Kijun
    if tenkan[idx] > kijun[idx]:
        score += 1
        signals.append("Tenkan > Kijun")
    
    # 2. Price above cloud
    if not np.isnan(span_a[idx]) and not np.isnan(span_b[idx]):
        cloud_top = max(span_a[idx], span_b[idx])
        if prices[idx] > cloud_top:
            score += 1
            signals.append("Price above cloud")
    
    # 3. Chikou above price (26 bars ago)
    if idx >= 26:
        score += 1
        signals.append("Chikou above price")
    
    # 4. Cloud is bullish (span_a > span_b, shifted 26)
    future_idx = idx + 26
    if future_idx < len(span_a) and not np.isnan(span_a[future_idx]) and not np.isnan(span_b[future_idx]):
        if span_a[future_idx] > span_b[future_idx]:
            score += 1
            signals.append("Bullish cloud")
    
    return score, signals


class IchimokuCloudScene(Scene):
    def construct(self, prices=None, title=None, pair="SOL", timeframe="4h",
                  show_signals=True, n_bars=80):
        """
        Render Ichimoku cloud chart.
        
        Args:
            prices: Array of close prices (None = load from OHLCV)
            title: Chart title (None = auto-generate)
            pair: Trading pair for data loading
            timeframe: Timeframe for data loading
            show_signals: Show entry signals
            n_bars: Number of bars to show
        """
        # Load real data if not provided
        if prices is None:
            ohlcv = load_ohlcv(pair=pair, timeframe="240m" if timeframe == "4h" else timeframe)
            if ohlcv is not None:
                # Take last n_bars
                prices = ohlcv['close'][-n_bars:]
                if title is None:
                    title = f"Ichimoku — {pair} {timeframe}"
            else:
                # Fallback to synthetic
                prices = generate_synthetic_prices(n_bars=n_bars)
                if title is None:
                    title = f"Ichimoku — {pair} {timeframe} (Sample)"
        
        if title is None:
            title = f"Ichimoku — {pair} {timeframe}"
        
        kijun_period = 26
        tenkan, kijun, span_a, span_b = compute_ichi(prices, kijun_period=kijun_period)
        n = len(prices)

        # TITLE
        self.add(header_text(title, size=SZ_TITLE).to_edge(UP, buff=0.15))

        # === LEFT COLUMN: Score + Criteria ===
        score_title = styled_text("ICHIMOKU SCORE", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.55)

        # Compute current score
        current_score, signals = compute_ichi_score(prices, -1)
        
        # Score box
        score_color = MANIM_GREEN if current_score >= 3 else MANIM_YELLOW if current_score >= 2 else MANIM_RED
        score_box = RoundedRectangle(
            width=2.4, height=0.5, corner_radius=0.04,
            color=score_color, fill_opacity=0.12, stroke_width=1,
        ).next_to(score_title, DOWN, buff=0.2)
        score_box.align_to(score_title, LEFT)
        score_val = mono_text(f"+{current_score} / 6", size=SZ_VALUE, color=score_color, weight="BOLD").move_to(score_box)

        # Criteria title
        criteria_title = styled_text("ENTRY SIGNALS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).next_to(score_box, DOWN, buff=0.3)
        criteria_title.align_to(score_title, LEFT)

        # Criteria list - show current state
        criteria = VGroup()
        criteria_items = [
            ("Tenkan > Kijun", tenkan[-1] > kijun[-1] if not np.isnan(tenkan[-1]) else False),
            ("Price above cloud", prices[-1] > max(span_a[-1], span_b[-1]) if not np.isnan(span_a[-1]) else False),
            ("Chikou above price", prices[-1] > prices[-26] if len(prices) > 26 else False),
            ("IchiScore >= 3", current_score >= 3),
        ]
        
        for text, is_true in criteria_items:
            icon = "✓" if is_true else "✗"
            color = MANIM_GREEN if is_true else MANIM_RED
            criteria.add(styled_text(f"{icon} {text}", size=SZ_LABEL, color=color, font=FONT_SANS))
        
        criteria.arrange(DOWN, aligned_edge=LEFT, buff=0.1)
        criteria.next_to(criteria_title, DOWN, buff=0.12)
        criteria.align_to(criteria_title, LEFT)

        # Legend title
        legend_title = styled_text("LEGEND", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).next_to(criteria, DOWN, buff=0.25)
        legend_title.align_to(score_title, LEFT)

        # Legend items
        legend_items = VGroup()
        for name, color in [("Tenkan", MANIM_RED), ("Kijun", MANIM_BLUE), ("Chikou", MANIM_PURPLE), ("Cloud ↑", MANIM_GREEN), ("Cloud ↓", MANIM_RED)]:
            swatch = Line(LEFT * 0.15, RIGHT * 0.15, color=color, stroke_width=3)
            lbl = styled_text(name, size=SZ_SMALL, color=MANIM_WHITE, font=FONT_SANS)
            item = VGroup(swatch, lbl).arrange(RIGHT, buff=0.08)
            legend_items.add(item)
        legend_items.arrange(DOWN, aligned_edge=LEFT, buff=0.06)
        legend_items.next_to(legend_title, DOWN, buff=0.1)
        legend_items.align_to(legend_title, LEFT)

        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)

        self.add(score_title, score_box, score_val, criteria_title, criteria, legend_title, legend_items, divider)

        # === RIGHT COLUMN: Cloud Chart ===
        price_min = np.nanmin(prices) - 5
        price_max = np.nanmax(prices) + 5
        axes = Axes(
            x_range=[0, n, 10],
            y_range=[price_min, price_max, (price_max - price_min) / 5],
            x_length=8.0,
            y_length=4.5,
            axis_config={"include_tip": False, "font_size": 12},
        ).shift(RIGHT * 0.8 + DOWN * 0.1)

        self.play(Create(axes), run_time=0.3)

        # Cloud
        cloud_displacement = 26
        cloud_polys = VGroup()
        for i in range(kijun_period, n - cloud_displacement):
            if np.isnan(span_a[i]) or np.isnan(span_b[i]):
                continue
            y_top, y_bot = max(span_a[i], span_b[i]), min(span_a[i], span_b[i])
            color = MANIM_GREEN if span_a[i] > span_b[i] else MANIM_RED
            poly = Polygon(
                axes.c2p(i, y_top), axes.c2p(i+1, y_top),
                axes.c2p(i+1, y_bot), axes.c2p(i, y_bot),
                fill_color=color, fill_opacity=0.12, stroke_width=0,
            )
            cloud_polys.add(poly)
        self.play(FadeIn(cloud_polys, lag_ratio=0.003), run_time=0.7)

        # Lines
        kijun_pts = [axes.c2p(i, kijun[i]) for i in range(kijun_period, n) if not np.isnan(kijun[i])]
        tenkan_pts = [axes.c2p(i, tenkan[i]) for i in range(kijun_period, n) if not np.isnan(tenkan[i])]

        kijun_line = VMobject(color=MANIM_BLUE, stroke_width=1.5)
        if len(kijun_pts) > 2:
            kijun_line.set_points_smoothly(kijun_pts)
        tenkan_line = VMobject(color=MANIM_RED, stroke_width=1.5)
        if len(tenkan_pts) > 2:
            tenkan_line.set_points_smoothly(tenkan_pts)
        self.play(Create(tenkan_line), Create(kijun_line), run_time=0.5)

        # Chikou
        chikou_pts = [axes.c2p(i - 26, prices[i]) for i in range(26, n)]
        chikou_line = VMobject(color=MANIM_PURPLE, stroke_width=1, stroke_opacity=0.5)
        if len(chikou_pts) > 2:
            chikou_line.set_points_smoothly(chikou_pts)
        self.play(Create(chikou_line), run_time=0.3)

        # Price
        price_points = [axes.c2p(i, prices[i]) for i in range(n)]
        price_line = VMobject(color=MANIM_WHITE, stroke_width=2)
        price_line.set_points_smoothly(price_points)
        self.play(Create(price_line), run_time=0.8, rate_func=linear)

        # Crossovers
        crossovers = []
        for i in range(kijun_period + 1, n):
            if np.isnan(tenkan[i]) or np.isnan(tenkan[i-1]) or np.isnan(kijun[i]) or np.isnan(kijun[i-1]):
                continue
            if tenkan[i-1] <= kijun[i-1] and tenkan[i] > kijun[i]:
                crossovers.append((i, "bullish"))
            elif tenkan[i-1] >= kijun[i-1] and tenkan[i] < kijun[i]:
                crossovers.append((i, "bearish"))
        
        # Show last 3 crossovers
        for bar, cross_type in crossovers[-3:]:
            pt = axes.c2p(bar, prices[bar])
            color = MANIM_GREEN if cross_type == "bullish" else MANIM_RED
            circle = Circle(radius=0.12, color=color, fill_opacity=0.25, stroke_width=1.5).move_to(pt)
            label = styled_text(
                "TK↑" if cross_type == "bullish" else "TK↓",
                size=SZ_SMALL, color=color, weight="BOLD", font=FONT_MONO,
            ).next_to(circle, UP, buff=0.06)
            self.play(FadeIn(circle), Write(label), run_time=0.15)

        self.wait(2)
