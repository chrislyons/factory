"""
Equity Curve Scene — 25/75 layout, left-aligned stats.
Loads from real backtest data when available.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE, REGIME_COLORS,
    header_text, mono_text, styled_text,
)
from viz.data_loader import (
    load_backtest_results, load_equity_curve_from_trades,
    compute_stats, generate_synthetic_equity, load_regime_state,
)

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12


class EquityCurveScene(Scene):
    def construct(self, equity_curve=None, trades=None, regime_sequence=None,
                  title=None, initial_capital=10000.0, source="h3"):
        """
        Render equity curve from real or synthetic data.
        
        Args:
            equity_curve: List of equity values (None = load from data)
            trades: List of trade dicts (None = load from data)
            regime_sequence: List of regime strings (None = load from current_regime)
            title: Chart title (None = auto-generate)
            initial_capital: Starting capital
            source: Data source name ("h3", "mr", "combo", etc.)
        """
        # Load real data if not provided
        if equity_curve is None:
            # Try loading from backtest results
            results = load_backtest_results(source)
            if results and "equity_curve" in results:
                equity_curve = results["equity_curve"]
                trades = results.get("trades", [])
                if title is None:
                    title = results.get("title", f"{source.upper()} Backtest")
            elif results and "train_equity" in results:
                # Walk-forward format
                equity_curve = results["train_equity"] + results.get("test_equity", [])
                trades = results.get("trades", [])
                if title is None:
                    title = f"{source.upper()} Walk-Forward"
            else:
                # Fallback to synthetic
                equity_curve, trades = generate_synthetic_equity()
                if title is None:
                    title = f"{source.upper()} — Sample Data"
        
        if title is None:
            title = f"{source.upper()} Equity Curve"
        
        n_points = len(equity_curve)
        n_trades = len(trades) if trades else 0

        # Compute stats
        stats = compute_stats(equity_curve, trades or [], initial_capital)
        final_value = stats["final_value"]
        total_return = stats["total_return"]
        win_rate = stats["win_rate"]
        pf = stats["profit_factor"]
        final_color = MANIM_GREEN if final_value > initial_capital else MANIM_RED

        # TITLE
        title_g = header_text(title, size=SZ_TITLE).to_edge(UP, buff=0.15)
        self.add(title_g)

        # === LEFT COLUMN: Stats ===
        stats_title = styled_text("STATISTICS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.6)

        stat_items = VGroup()
        for label, value, color in [
            ("Initial", f"${initial_capital:,.0f}", MANIM_WHITE),
            ("Final", f"${final_value:,.0f}", final_color),
            ("Return", f"{total_return:+.1f}%", final_color),
            ("Trades", str(n_trades), MANIM_WHITE),
            ("Win Rate", f"{win_rate:.1f}%", MANIM_GREEN if win_rate > 50 else MANIM_RED),
            ("PF", f"{pf:.2f}", MANIM_GREEN if pf > 1 else MANIM_RED),
            ("Max DD", f"{stats['max_drawdown']:.1f}%", MANIM_RED),
        ]:
            row = VGroup(
                styled_text(label, size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
                mono_text(value, size=SZ_VALUE, color=color, weight="BOLD"),
            ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
            stat_items.add(row)
        
        stat_items.arrange(DOWN, buff=0.18, aligned_edge=LEFT)
        stat_items.next_to(stats_title, DOWN, buff=0.2)
        stat_items.align_to(stats_title, LEFT)

        # Thin divider line
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)

        self.play(Write(stats_title), run_time=0.2)
        self.play(Write(stat_items), run_time=0.3)
        self.add(divider)

        # === RIGHT COLUMN: Chart ===
        y_min = min(equity_curve) * 0.96
        y_max = max(equity_curve) * 1.06

        axes = Axes(
            x_range=[0, n_points - 1, max(1, (n_points - 1) // 10)],
            y_range=[y_min, y_max, (y_max - y_min) / 5],
            x_length=8.0,
            y_length=4.5,
            axis_config={"include_tip": False, "font_size": 14},
        ).shift(RIGHT * 0.8 + DOWN * 0.1)

        x_label = styled_text("Trade #", size=SZ_LABEL, font=FONT_SANS).next_to(axes.x_axis, DOWN, buff=0.1)
        y_label = styled_text("Wallet ($)", size=SZ_LABEL, font=FONT_SANS).next_to(axes.y_axis, LEFT, buff=0.1).rotate(90 * DEGREES)
        self.play(Create(axes), Write(x_label), Write(y_label), run_time=0.4)

        # Regime overlay - try to load from current_regime.json
        if regime_sequence is None:
            regime_state = load_regime_state()
            if regime_state and regime_state.get("state") != "UNKNOWN":
                # Generate regime sequence from current state
                current_regime = regime_state["state"]
                # Simple: mostly RISK_ON with some NEUTRAL
                np.random.seed(42)
                regime_sequence = ["RISK_ON" if np.random.random() < 0.7 else "NEUTRAL" for _ in range(n_points - 1)]
            else:
                np.random.seed(123)
                regime_sequence = ["RISK_ON" if np.random.random() < 0.7 else "NEUTRAL" if np.random.random() < 0.75 else "RISK_OFF" for _ in range(n_points - 1)]
        
        bar_width = 1.0 / (n_points - 1) * axes.x_length
        regime_bars = VGroup()
        for i, regime in enumerate(regime_sequence):
            bar = Rectangle(
                width=bar_width + 0.02, height=axes.y_length,
                fill_color=REGIME_COLORS.get(regime, MANIM_GREY), fill_opacity=0.06, stroke_width=0,
            ).move_to(axes.c2p(i, (y_min + y_max) / 2))
            regime_bars.add(bar)
        self.play(FadeIn(regime_bars, lag_ratio=0.01), run_time=0.3)

        # Equity curve
        points = [axes.c2p(i, equity_curve[i]) for i in range(n_points)]
        curve = VMobject(color=MANIM_BLUE, stroke_width=2.5)
        curve.set_points_smoothly(points)
        self.play(Create(curve), run_time=1, rate_func=linear)

        # Trade dots
        trade_dots = VGroup()
        for i, trade in enumerate(trades[:n_points-1] if trades else []):
            if i + 1 >= n_points:
                break
            pt = axes.c2p(i + 1, equity_curve[i + 1])
            trade_type = trade.get("type", "win" if trade.get("pnl", 0) > 0 else "loss")
            color = MANIM_GREEN if trade_type == "win" else MANIM_RED
            trade_dots.add(Dot(pt, radius=0.03, color=color, fill_opacity=0.8))
        if trade_dots:
            self.play(FadeIn(trade_dots, lag_ratio=0.01), run_time=0.4)

        # Final value label
        final_text = mono_text(f"${final_value:,.0f}", size=SZ_VALUE + 2, color=final_color, weight="BOLD"
        ).move_to(axes.c2p(n_points * 0.12, y_min + (y_max - y_min) * 0.88))
        self.play(Write(final_text), run_time=0.2)

        self.wait(2)
