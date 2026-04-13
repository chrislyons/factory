"""
Backtest Comparison — 25/75 layout, walk-forward visualization.
Loads real walk-forward results when available.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE,
    header_text, mono_text, styled_text,
)
from viz.data_loader import load_backtest_results, generate_synthetic_equity

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12


def generate_synthetic_wf(n_train=30, n_test=15, train_pf=4.0, test_pf=3.5, seed=42):
    """Fallback: generate synthetic walk-forward curves."""
    rng = np.random.default_rng(seed)
    
    def make_curve(n, pf):
        wallet = 10000
        equity = [wallet]
        for _ in range(n):
            pnl = wallet * 0.02 * (pf / 2) if rng.random() < 0.55 else -wallet * 0.02
            wallet += pnl
            equity.append(wallet)
        return equity
    
    return make_curve(n_train, train_pf), make_curve(n_test, test_pf)


class BacktestComparisonScene(Scene):
    def construct(self, train_equity=None, test_equity=None, train_stats=None, test_stats=None,
                  title=None, source="h3"):
        """
        Render walk-forward backtest comparison.
        
        Args:
            train_equity: Training equity curve (None = load from data)
            test_equity: Test equity curve (None = load from data)
            train_stats: Training stats dict (None = compute from equity)
            test_stats: Test stats dict (None = compute from equity)
            title: Chart title (None = auto-generate)
            source: Data source name
        """
        # Load real data if not provided
        if train_equity is None:
            results = load_backtest_results(source)
            if results and "train_equity" in results and "test_equity" in results:
                train_equity = results["train_equity"]
                test_equity = results["test_equity"]
                train_stats = results.get("train_stats", {})
                test_stats = results.get("test_stats", {})
                if title is None:
                    title = results.get("title", f"{source.upper()} Walk-Forward")
            elif results and "oos_pf" in results:
                # Single backtest with IS/OOS split
                train_equity = results.get("is_equity", [])
                test_equity = results.get("oos_equity", [])
                train_stats = {"PF": results.get("is_pf", 4.0), "WR": results.get("is_wr", 55), "n": results.get("is_n", 30)}
                test_stats = {"PF": results.get("oos_pf", 3.0), "WR": results.get("oos_wr", 53), "n": results.get("oos_n", 50)}
                if title is None:
                    title = f"{source.upper()} Validation"
            else:
                # Fallback to synthetic
                train_equity, test_equity = generate_synthetic_wf()
                train_stats = {"PF": 4.12, "WR": 58.3, "n": 30, "p": 0.001}
                test_stats = {"PF": 3.13, "WR": 57.7, "n": 52, "p": 0.000}
                if title is None:
                    title = f"{source.upper()} — Sample Walk-Forward"
        
        if title is None:
            title = f"{source.upper()} Walk-Forward"
        
        if train_stats is None:
            train_stats = {"PF": 4.0, "WR": 55, "n": len(train_equity) - 1}
        if test_stats is None:
            test_stats = {"PF": 3.0, "WR": 53, "n": len(test_equity) - 1}

        train_pf = train_stats.get("PF", 4.0)
        test_pf = test_stats.get("PF", 3.0)
        pf_ratio = test_pf / train_pf if train_pf > 0 else 0
        if pf_ratio >= 0.6:
            verdict, verdict_color, verdict_icon = "PASS", MANIM_GREEN, "✓"
        else:
            verdict, verdict_color, verdict_icon = "WARN", MANIM_YELLOW, "!"

        # TITLE
        self.add(header_text(title, size=SZ_TITLE).to_edge(UP, buff=0.15))

        # === LEFT COLUMN: Validation ===
        val_title = styled_text("VALIDATION", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.55)

        left_items = VGroup()
        for label, value, color in [
            ("Train PF", f"{train_pf:.2f}", MANIM_BLUE),
            ("OOS PF", f"{test_pf:.2f}", MANIM_GREEN),
            ("OOS/IS", f"{pf_ratio:.0%}", verdict_color),
            ("Train n", str(train_stats.get("n", 0)), MANIM_WHITE),
            ("Train WR", f"{train_stats.get('WR', 0):.1f}%", MANIM_WHITE),
            ("OOS n", str(test_stats.get("n", 0)), MANIM_WHITE),
            ("OOS WR", f"{test_stats.get('WR', 0):.1f}%", MANIM_WHITE),
            ("p-value", f"{test_stats.get('p', 0):.3f}", MANIM_WHITE),
        ]:
            row = VGroup(
                styled_text(label, size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
                mono_text(value, size=SZ_VALUE, color=color, weight="BOLD"),
            ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
            left_items.add(row)
        left_items.arrange(DOWN, buff=0.14, aligned_edge=LEFT)
        left_items.next_to(val_title, DOWN, buff=0.2)
        left_items.align_to(val_title, LEFT)

        # Verdict box
        verdict_box = RoundedRectangle(
            width=2.6, height=0.5, corner_radius=0.04,
            color=verdict_color, fill_opacity=0.12,
        ).next_to(left_items, DOWN, buff=0.2)
        verdict_box.align_to(left_items, LEFT)
        verdict_label = mono_text(f"{verdict_icon} {verdict}", size=SZ_VALUE, color=verdict_color, weight="BOLD"
        ).move_to(verdict_box)

        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)

        self.add(val_title, left_items, verdict_box, verdict_label, divider)

        # === RIGHT COLUMN: Split Chart ===
        train_label = styled_text("IN-SAMPLE", size=SZ_SMALL, color=MANIM_BLUE, weight="BOLD", font=FONT_SANS
        ).shift(LEFT * 0.3 + UP * 2.4)
        test_label = styled_text("OUT-OF-SAMPLE", size=SZ_SMALL, color=MANIM_GREEN, weight="BOLD", font=FONT_SANS
        ).shift(RIGHT * 3.8 + UP * 2.4)

        # Train axes
        train_axes = Axes(
            x_range=[0, len(train_equity) - 1, max(1, len(train_equity) // 5)],
            y_range=[min(train_equity) * 0.96, max(train_equity) * 1.04, 500],
            x_length=3.8, y_length=4.5,
            axis_config={"include_tip": False, "font_size": 12},
        ).shift(LEFT * 0.3 + DOWN * 0.1)

        train_points = [train_axes.c2p(i, v) for i, v in enumerate(train_equity)]
        train_curve = VMobject(color=MANIM_BLUE, stroke_width=2.5)
        if len(train_points) > 2:
            train_curve.set_points_smoothly(train_points)

        # Test axes
        test_axes = Axes(
            x_range=[0, len(test_equity) - 1, max(1, len(test_equity) // 3)],
            y_range=[min(test_equity) * 0.96, max(test_equity) * 1.04, 200],
            x_length=3.8, y_length=4.5,
            axis_config={"include_tip": False, "font_size": 12},
        ).shift(RIGHT * 3.8 + DOWN * 0.1)

        test_points = [test_axes.c2p(i, v) for i, v in enumerate(test_equity)]
        test_curve = VMobject(color=MANIM_GREEN, stroke_width=2.5)
        if len(test_points) > 2:
            test_curve.set_points_smoothly(test_points)

        self.play(
            Create(train_axes), Create(train_curve),
            Create(test_axes), Create(test_curve),
            Write(train_label), Write(test_label),
            run_time=1
        )

        # Mini stats
        train_mini = VGroup(
            mono_text(f"PF {train_pf:.2f}", size=SZ_SMALL, color=MANIM_BLUE),
            styled_text(f"WR {train_stats.get('WR', 0):.1f}%", size=SZ_SMALL, color=MANIM_WHITE, font=FONT_MONO),
        ).arrange(RIGHT, buff=0.15).next_to(train_axes, DOWN, buff=0.12)

        test_mini = VGroup(
            mono_text(f"PF {test_pf:.2f}", size=SZ_SMALL, color=MANIM_GREEN),
            styled_text(f"WR {test_stats.get('WR', 0):.1f}%", size=SZ_SMALL, color=MANIM_WHITE, font=FONT_MONO),
        ).arrange(RIGHT, buff=0.15).next_to(test_axes, DOWN, buff=0.12)

        self.play(Write(train_mini), Write(test_mini), run_time=0.2)

        # Arrow
        arrow = Arrow(
            train_axes.get_right() + RIGHT * 0.05,
            test_axes.get_left() + LEFT * 0.05,
            color=verdict_color, stroke_width=2, buff=0.05,
        )
        pf_change = mono_text(f"{train_pf:.2f}→{test_pf:.2f}", size=SZ_SMALL, color=verdict_color
        ).next_to(arrow, UP, buff=0.05)

        self.play(GrowArrow(arrow), Write(pf_change), run_time=0.3)

        self.wait(2)
