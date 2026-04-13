"""
Mean Reversion Validation Scene — 25/75 layout.
Loads actual MR validation data when available.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import json
import numpy as np
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE, MANIM_PURPLE,
    header_text, mono_text, styled_text,
)
from viz.data_loader import load_json, DATA_DIR

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12

# Fallback data from IG88037 when no real data available
FALLBACK_MR_DATA = {
    'pairs': ['NEAR', 'ETH', 'SOL', 'LINK', 'AVAX', 'BTC'],
    'pf': [3.38, 3.28, 3.21, 3.15, 2.54, 2.47],
    'wr': [43.6, 51.2, 43.5, 45.1, 39.8, 47.6],
    'exp': [1.88, 1.50, 1.73, 1.66, 1.29, 1.00],
    'n': [397, 424, 448, 406, 455, 431],
}

FALLBACK_STOP_TARGET = [
    ('2%/3%', 2.29, 68.1, 0.98),
    ('1.5%/3%', 2.53, 65.2, 1.01),
    ('1%/7.5%', 3.21, 43.5, 1.73),
    ('0.5%/7.5%', 4.14, 38.8, 1.76),
    ('Adaptive', 3.69, 47.5, 1.90),
]

FALLBACK_REGIME_DATA = {
    'labels': ['<2% ATR', '2-4% ATR', '>4% ATR'],
    'pf': [1.70, 2.84, 9.75],
    'exp': [0.58, 1.49, 3.52],
}


def load_mr_data():
    """Load MR validation results from data files."""
    # Try multiple data sources
    paths = [
        DATA_DIR / "mr_results.json",
        DATA_DIR / "mr_validation.json",
        DATA_DIR / "mr_optimized_results.json",
    ]
    
    for path in paths:
        data = load_json(path)
        if data:
            return data
    return None


def extract_mr_pair_data(mr_data):
    """Extract pair-level PF, WR, exp, n from MR data."""
    if "pair_results" in mr_data:
        pairs = []
        pfs = []
        wrs = []
        exps = []
        ns = []
        for pair, results in mr_data["pair_results"].items():
            pairs.append(pair.replace("USDT", "").replace("-", ""))
            pfs.append(results.get("pf", 0))
            wrs.append(results.get("win_rate", 0))
            exps.append(results.get("expectancy", 0))
            ns.append(results.get("n_trades", 0))
        if pairs:
            # Sort by PF descending
            sorted_data = sorted(zip(pfs, pairs, wrs, exps, ns), reverse=True)
            return {
                'pairs': [x[1] for x in sorted_data],
                'pf': [x[0] for x in sorted_data],
                'wr': [x[2] for x in sorted_data],
                'exp': [x[3] for x in sorted_data],
                'n': [x[4] for x in sorted_data],
            }
    return None


class MRValidationScene(Scene):
    """Scene showing Mean Reversion validation results across all pairs."""
    
    def construct(self, pair_data=None, stats=None, title=None):
        """
        Render MR validation results.
        
        Args:
            pair_data: Dict with pairs, pf, wr, exp, n (None = load from data)
            stats: Dict with aggregate stats (None = compute from pair_data)
            title: Title string (None = auto-generate)
        """
        # Load real data if not provided
        if pair_data is None:
            mr_data = load_mr_data()
            if mr_data:
                pair_data = extract_mr_pair_data(mr_data)
                if stats is None:
                    stats = {
                        "total_trades": mr_data.get("total_trades", 0),
                        "aggregate_pf": mr_data.get("aggregate_pf", 0),
                        "ci_90": mr_data.get("confidence_interval", "[N/A]"),
                        "p_value": mr_data.get("p_value", "< 0.001"),
                        "avg_win_rate": mr_data.get("avg_win_rate", 0),
                        "avg_expectancy": mr_data.get("avg_expectancy", 0),
                    }
                if title is None:
                    title = mr_data.get("title", "Mean Reversion Validation")
            
            if pair_data is None:
                # Use fallback data
                pair_data = FALLBACK_MR_DATA
                if stats is None:
                    stats = {
                        "total_trades": 2561,
                        "aggregate_pf": 3.39,
                        "ci_90": "[3.15, 3.64]",
                        "p_value": "< 0.00000001",
                        "avg_win_rate": 45.1,
                        "avg_expectancy": 1.51,
                    }
                if title is None:
                    title = "Mean Reversion — Sample Data"
        
        if title is None:
            title = "Mean Reversion Validation Results"
        if stats is None:
            total_trades = sum(pair_data.get('n', []))
            stats = {
                "total_trades": total_trades,
                "aggregate_pf": np.mean(pair_data.get('pf', [0])),
                "ci_90": "N/A",
                "p_value": "< 0.001",
                "avg_win_rate": np.mean(pair_data.get('wr', [0])),
                "avg_expectancy": np.mean(pair_data.get('exp', [0])),
            }

        # TITLE
        title_text = header_text(title, size=SZ_TITLE).to_edge(UP, buff=0.15)
        subtitle = styled_text(
            f"{stats.get('total_trades', 0):,} Trades | {len(pair_data.get('pairs', []))} Pairs | p {stats.get('p_value', '< 0.001')}",
            size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).next_to(title_text, DOWN, buff=0.05)
        self.add(title_text, subtitle)
        
        # === LEFT COLUMN: Stats ===
        stats_title = styled_text("KEY METRICS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.8)
        
        # Find best pair
        best_pair_idx = np.argmax(pair_data.get('pf', [0]))
        best_pair = pair_data['pairs'][best_pair_idx] if pair_data.get('pairs') else "N/A"
        best_pf = pair_data['pf'][best_pair_idx] if pair_data.get('pf') else 0
        
        stat_items = VGroup()
        for label, value, color in [
            ("Total Trades", f"{stats.get('total_trades', 0):,}", MANIM_WHITE),
            ("Aggregate PF", f"{stats.get('aggregate_pf', 0):.2f}", MANIM_GREEN),
            ("90% CI", stats.get('ci_90', 'N/A'), MANIM_WHITE),
            ("p-value", stats.get('p_value', '< 0.001'), MANIM_GREEN),
            ("Avg Win Rate", f"{stats.get('avg_win_rate', 0):.1f}%", MANIM_YELLOW),
            ("Avg Expectancy", f"{stats.get('avg_expectancy', 0):.2f}%", MANIM_GREEN),
            ("Best Pair", f"{best_pair} ({best_pf:.2f})", MANIM_PURPLE),
        ]:
            row = VGroup(
                styled_text(label, size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                mono_text(value, size=SZ_SMALL, color=color, weight="BOLD"),
            ).arrange(RIGHT, buff=0.15, aligned_edge=DOWN)
            stat_items.add(row)
        
        stat_items.arrange(DOWN, buff=0.12, aligned_edge=LEFT)
        stat_items.next_to(stats_title, DOWN, buff=0.2)
        stat_items.align_to(stats_title, LEFT)
        
        self.play(Write(stats_title), run_time=0.2)
        self.play(Write(stat_items), run_time=0.5)
        
        # Thin divider
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)
        self.add(divider)
        
        # === RIGHT COLUMN: PF Bar Chart ===
        chart_title_text = header_text("Profit Factor by Pair", size=SZ_LABEL, color=MANIM_YELLOW
        ).shift(RIGHT * 0.8 + UP * 0.6)
        self.play(Write(chart_title_text), run_time=0.2)
        
        # Bar chart for PF
        bar_group = VGroup()
        bar_width = 0.6
        spacing = 0.9
        max_pf = max(pair_data.get('pf', [1]))
        
        for i, (pair, pf) in enumerate(zip(pair_data.get('pairs', []), pair_data.get('pf', []))):
            bar_height = (pf / max_pf) * 2.5
            color = MANIM_GREEN if pf >= 3.0 else MANIM_YELLOW if pf >= 2.5 else MANIM_RED
            
            bar = Rectangle(
                width=bar_width,
                height=bar_height,
                fill_color=color,
                fill_opacity=0.8,
                stroke_color=MANIM_WHITE,
                stroke_width=0.5,
            )
            
            x_pos = -2.0 + i * spacing
            bar.move_to(RIGHT * x_pos + UP * (bar_height / 2 - 1.2))
            
            label = styled_text(pair, size=SZ_SMALL, font=FONT_MONO
            ).next_to(bar, DOWN, buff=0.1)
            
            pf_val = mono_text(f"{pf:.2f}", size=SZ_SMALL, color=color, weight="BOLD"
            ).next_to(bar, UP, buff=0.05)
            
            bar_group.add(bar, label, pf_val)
        
        self.play(FadeIn(bar_group, lag_ratio=0.05), run_time=0.8)
        self.wait(2)


class MRConfigComparisonScene(Scene):
    """Scene comparing different stop/target configurations."""
    
    def construct(self, config_data=None, title=None):
        """Render stop/target configuration comparison."""
        
        # Try to load actual optimization data
        if config_data is None:
            opt_data = load_json(DATA_DIR / "mr_optimization.json")
            if opt_data and "configurations" in opt_data:
                config_data = []
                for cfg in opt_data["configurations"]:
                    config_data.append((
                        cfg.get("name", cfg.get("config", "?")),
                        cfg.get("pf", 0),
                        cfg.get("win_rate", 0),
                        cfg.get("expectancy", 0),
                    ))
                if title is None:
                    title = "Stop/Target Optimization"
            
            if config_data is None:
                config_data = FALLBACK_STOP_TARGET
                if title is None:
                    title = "Stop/Target Configuration Comparison"
        
        if title is None:
            title = "Stop/Target Configuration Comparison"
        
        # TITLE
        title_text = header_text(title, size=SZ_TITLE).to_edge(UP, buff=0.15)
        subtitle = header_text("SOL 4h | MR Strategy | Adaptive Stops", size=SZ_SMALL, color=MANIM_GREY
        ).next_to(title_text, DOWN, buff=0.05)
        self.add(title_text, subtitle)
        
        # === LEFT COLUMN: Findings ===
        findings_title = styled_text("KEY FINDINGS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.8)
        
        # Find best config
        best = max(config_data, key=lambda x: x[3])  # Max expectancy
        
        findings = VGroup(
            styled_text(f"1. Best: {best[0]}", size=SZ_SMALL, color=MANIM_GREEN, font=FONT_SANS),
            styled_text(f"   Expectancy {best[3]:.2f}%", size=SZ_SMALL, color=MANIM_GREY, font=FONT_MONO),
            styled_text("2. Tight stops + wide targets", size=SZ_SMALL, color=MANIM_GREEN, font=FONT_SANS),
            styled_text("   Fail fast, run winners", size=SZ_SMALL, color=MANIM_GREY, font=FONT_MONO),
            styled_text(f"3. PF range: {min(c[1] for c in config_data):.2f} - {max(c[1] for c in config_data):.2f}", 
                       size=SZ_SMALL, color=MANIM_YELLOW, font=FONT_SANS),
        ).arrange(DOWN, buff=0.12, aligned_edge=LEFT)
        findings.next_to(findings_title, DOWN, buff=0.3)
        findings.align_to(findings_title, LEFT)
        
        self.play(Write(findings_title), run_time=0.2)
        self.play(Write(findings), run_time=0.6)
        
        # Thin divider
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)
        self.add(divider)
        
        # === RIGHT COLUMN: Comparison Table ===
        table_title_text = header_text("Configuration Comparison", size=SZ_LABEL, color=MANIM_YELLOW
        ).shift(RIGHT * 0.8 + UP * 0.8)
        self.play(Write(table_title_text), run_time=0.2)
        
        # Table header
        headers = ["Config", "PF", "WR", "Exp%"]
        
        header_row = VGroup(*[
            styled_text(h, size=SZ_SMALL, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS)
            for h in headers
        ]).arrange(RIGHT, buff=0.3)
        header_row.shift(RIGHT * 0.8 + UP * 0.4)
        self.play(Write(header_row), run_time=0.2)
        
        # Table rows
        for i, (config, pf, wr, exp) in enumerate(config_data):
            y_pos = 0.4 - (i + 1) * 0.45
            is_best = config == best[0]
            
            row_color = MANIM_PURPLE if is_best else MANIM_WHITE
            
            row = VGroup(
                styled_text(config, size=SZ_SMALL, color=row_color, weight="BOLD" if is_best else "NORMAL", font=FONT_MONO),
                mono_text(f"{pf:.2f}", size=SZ_SMALL, color=MANIM_GREEN if pf > 3 else MANIM_YELLOW),
                mono_text(f"{wr:.1f}%", size=SZ_SMALL, color=MANIM_WHITE),
                mono_text(f"{exp:.2f}%", size=SZ_SMALL, color=MANIM_GREEN if exp > 1.5 else MANIM_YELLOW),
            ).arrange(RIGHT, buff=0.3)
            row.shift(RIGHT * 0.8 + UP * y_pos)
            
            if is_best:
                highlight = SurroundingRectangle(row, color=MANIM_PURPLE, stroke_width=1, buff=0.1)
                self.play(FadeIn(row), Create(highlight), run_time=0.15)
            else:
                self.play(FadeIn(row), run_time=0.1)
        
        winner = header_text("WINNER: Highest Expectancy", size=SZ_SMALL, color=MANIM_PURPLE
        ).shift(RIGHT * 0.8 + DOWN * 2.0)
        self.play(Write(winner), run_time=0.2)
        
        self.wait(2)


class MRRegimeScene(Scene):
    """Scene showing regime-specific performance."""
    
    def construct(self, regime_data=None, title=None):
        """Render regime-specific performance."""
        
        # Try to load actual regime data
        if regime_data is None:
            regime_results = load_json(DATA_DIR / "mr_regime_results.json")
            if regime_results and "regimes" in regime_results:
                regime_data = {
                    'labels': [],
                    'pf': [],
                    'exp': [],
                }
                for regime in regime_results["regimes"]:
                    regime_data['labels'].append(regime.get("label", "?"))
                    regime_data['pf'].append(regime.get("pf", 0))
                    regime_data['exp'].append(regime.get("expectancy", 0))
                if title is None:
                    title = "Mean Reversion by Volatility Regime"
            
            if regime_data is None:
                regime_data = FALLBACK_REGIME_DATA
                if title is None:
                    title = "Mean Reversion by Volatility Regime (Sample)"
        
        if title is None:
            title = "Mean Reversion by Volatility Regime"
        
        # TITLE
        title_text = header_text(title, size=SZ_TITLE).to_edge(UP, buff=0.15)
        subtitle = header_text("SOL 4h | Regime-Adaptive Stops", size=SZ_SMALL, color=MANIM_GREY
        ).next_to(title_text, DOWN, buff=0.05)
        self.add(title_text, subtitle)
        
        # === LEFT COLUMN: Regime Config ===
        config_title = styled_text("REGIME CONFIGURATION", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.8)
        
        config_items = VGroup(
            styled_text("Low Vol (<2% ATR)", size=SZ_SMALL, color=MANIM_BLUE, font=FONT_SANS),
            mono_text("Stop: 1.5%  Target: 3.0%", size=SZ_SMALL, color=MANIM_WHITE),
            styled_text("Mid Vol (2-4% ATR)", size=SZ_SMALL, color=MANIM_YELLOW, font=FONT_SANS),
            mono_text("Stop: 1.0%  Target: 7.5%", size=SZ_SMALL, color=MANIM_WHITE),
            styled_text("High Vol (>4% ATR)", size=SZ_SMALL, color=MANIM_RED, font=FONT_SANS),
            mono_text("Stop: 0.5%  Target: 7.5%", size=SZ_SMALL, color=MANIM_WHITE),
        ).arrange(DOWN, buff=0.15, aligned_edge=LEFT)
        config_items.next_to(config_title, DOWN, buff=0.3)
        config_items.align_to(config_title, LEFT)
        
        # Find best regime
        best_regime_idx = np.argmax(regime_data.get('pf', [0]))
        best_regime = regime_data['labels'][best_regime_idx] if regime_data.get('labels') else "High Vol"
        best_pf = regime_data['pf'][best_regime_idx] if regime_data.get('pf') else 0
        
        insight = styled_text(f"Key: {best_regime} drives\n{best_pf:.1f}x returns for MR", 
                            size=SZ_SMALL, color=MANIM_GREEN, font=FONT_SANS
        ).next_to(config_items, DOWN, buff=0.4)
        insight.align_to(config_items, LEFT)
        
        self.play(Write(config_title), run_time=0.2)
        self.play(Write(config_items), run_time=0.4)
        self.play(Write(insight), run_time=0.3)
        
        # Thin divider
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)
        self.add(divider)
        
        # === RIGHT COLUMN: Regime Performance Chart ===
        chart_title_text = header_text("Profit Factor by Regime", size=SZ_LABEL, color=MANIM_YELLOW
        ).shift(RIGHT * 0.8 + UP * 0.6)
        self.play(Write(chart_title_text), run_time=0.2)
        
        # Bar chart
        bar_group = VGroup()
        bar_width = 1.2
        spacing = 2.0
        max_pf = max(regime_data.get('pf', [1]))
        
        colors = [MANIM_BLUE, MANIM_YELLOW, MANIM_RED]
        
        for i, (label, pf, color) in enumerate(zip(regime_data.get('labels', []), regime_data.get('pf', []), colors)):
            bar_height = (pf / max_pf) * 2.8
            
            bar = Rectangle(
                width=bar_width,
                height=bar_height,
                fill_color=color,
                fill_opacity=0.7,
                stroke_color=MANIM_WHITE,
                stroke_width=0.5,
            )
            
            x_pos = -2.0 + i * spacing
            bar.move_to(RIGHT * x_pos + UP * (bar_height / 2 - 1.5))
            
            label_below = styled_text(label, size=SZ_SMALL, font=FONT_MONO
            ).next_to(bar, DOWN, buff=0.15)
            
            pf_val = mono_text(f"PF {pf:.2f}", size=SZ_LABEL, color=color, weight="BOLD"
            ).next_to(bar, UP, buff=0.1)
            
            exp_val = mono_text(f"Exp {regime_data.get('exp', [0])[i]:.2f}%", size=SZ_SMALL, color=MANIM_GREY
            ).next_to(pf_val, UP, buff=0.05)
            
            bar_group.add(bar, label_below, pf_val, exp_val)
        
        self.play(FadeIn(bar_group, lag_ratio=0.05), run_time=0.8)
        
        # Highlight best regime
        highlight_text = header_text(f"{best_pf:.1f}x", size=SZ_TITLE, color=MANIM_RED
        ).next_to(bar_group[best_regime_idx * 4 + 2], UP, buff=0.4)
        self.play(Write(highlight_text), run_time=0.3)
        
        self.wait(2)
