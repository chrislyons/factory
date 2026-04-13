"""
Walk-Forward Decay Scene — 25/75 layout.
Shows PF by rolling window, overlays train/test PF, calculates degradation slope.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
try:
    import pandas as pd
except ImportError:
    pd = None
import json
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE,
    header_text, mono_text, styled_text,
)

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12


def load_walkforward_data():
    """Load walk-forward trades from CSV or generate synthetic data."""
    try:
        df = pd.read_csv('/Users/nesbitt/dev/factory/agents/ig88/data/walkforward_trades.csv')
        
        # Group by window
        windows = df['window'].unique()
        window_data = {}
        
        for w in windows:
            window_trades = df[df['window'] == w]
            
            # Compute stats for train (first 70%) and test (last 30%)
            n_trades = len(window_trades)
            train_end = int(n_trades * 0.7)
            
            train_trades = window_trades.iloc[:train_end]
            test_trades = window_trades.iloc[train_end:]
            
            # Compute profit factor for train
            train_wins = train_trades[train_trades['return_pct'] > 0]['return_pct'].sum()
            train_losses = abs(train_trades[train_trades['return_pct'] < 0]['return_pct'].sum())
            train_pf = train_wins / train_losses if train_losses > 0 else 2.0
            
            # Compute profit factor for test
            test_wins = test_trades[test_trades['return_pct'] > 0]['return_pct'].sum()
            test_losses = abs(test_trades[test_trades['return_pct'] < 0]['return_pct'].sum())
            test_pf = test_wins / test_losses if test_losses > 0 else 2.0
            
            window_data[int(w)] = {
                'train_pf': train_pf,
                'test_pf': test_pf,
                'train_n': len(train_trades),
                'test_n': len(test_trades),
            }
        
        return window_data
    
    except Exception as e:
        print(f"Error loading walkforward data: {e}")
        return None


def generate_synthetic_walkforward(n_windows=10):
    """Generate synthetic walk-forward data for demo."""
    rng = np.random.default_rng(42)
    
    window_data = {}
    base_train_pf = 2.5
    base_test_pf = 2.0
    
    for i in range(1, n_windows + 1):
        # Add decay and noise
        decay_factor = 0.95 ** i
        noise = rng.standard_normal() * 0.3
        
        train_pf = base_train_pf * decay_factor + noise
        test_pf = base_test_pf * decay_factor * (0.8 + rng.random() * 0.2)
        
        window_data[i] = {
            'train_pf': max(0.5, train_pf),
            'test_pf': max(0.3, test_pf),
            'train_n': 20 + int(rng.random() * 10),
            'test_n': 8 + int(rng.random() * 5),
        }
    
    return window_data


def compute_degradation_slope(train_pfs, test_pfs):
    """Compute degradation slope (OOS/IS ratio trend)."""
    if len(train_pfs) < 2:
        return 0.0, 1.0
    
    # OOS/IS ratios
    ratios = []
    for train_pf, test_pf in zip(train_pfs, test_pfs):
        if train_pf > 0:
            ratios.append(test_pf / train_pf)
        else:
            ratios.append(0.0)
    
    # Linear regression slope
    x = np.arange(len(ratios))
    if np.std(x) > 0:
        slope = np.polyfit(x, ratios, 1)[0]
    else:
        slope = 0.0
    
    avg_ratio = np.mean(ratios) if ratios else 1.0
    
    return slope, avg_ratio


def load_h3ev2_walkforward():
    """Load h3ev2 walkforward results."""
    try:
        with open('/Users/nesbitt/dev/factory/agents/ig88/data/h3ev2_walkforward_results.json', 'r') as f:
            data = json.load(f)
        
        window_data = {}
        for window_info in data.get('windows', []):
            w = window_info['window']
            window_data[w] = {
                'train_pf': window_info['train']['pf'],
                'test_pf': window_info['test']['pf'],
                'train_n': window_info['train']['n'],
                'test_n': window_info['test']['n'],
            }
        
        return window_data
    except Exception as e:
        print(f"Error loading h3ev2 walkforward: {e}")
        return None


class WalkForwardDecayScene(Scene):
    def construct(self):
        """
        Render walk-forward decay analysis.
        Left: Degradation stats and alerts.
        Right: PF by window with train/test overlay.
        """
        self.camera.background_color = "#09090b"
        
        # Load walk-forward data
        window_data = load_h3ev2_walkforward()
        if window_data is None or len(window_data) < 3:
            window_data = load_walkforward_data()
        if window_data is None or len(window_data) < 3:
            window_data = generate_synthetic_walkforward(8)
        
        # Extract arrays
        windows = sorted(window_data.keys())
        train_pfs = [window_data[w]['train_pf'] for w in windows]
        test_pfs = [window_data[w]['test_pf'] for w in windows]
        train_ns = [window_data[w]['train_n'] for w in windows]
        test_ns = [window_data[w]['test_n'] for w in windows]
        
        # Compute metrics
        slope, avg_ratio = compute_degradation_slope(train_pfs, test_pfs)
        
        # Overall stats
        overall_train_pf = np.mean(train_pfs)
        overall_test_pf = np.mean(test_pfs)
        final_train_pf = train_pfs[-1]
        final_test_pf = test_pfs[-1]
        
        # Check for decay alert
        is_decay_alert = avg_ratio < 0.6
        
        # === TITLE ===
        title = header_text("WALK-FORWARD DECAY", size=SZ_TITLE).to_edge(UP, buff=0.15)
        self.add(title)
        
        # === LEFT COLUMN: Stats ===
        stats_title = styled_text("DECAY METRICS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.6)
        
        # Overall PF stats
        train_pf_color = MANIM_GREEN if overall_train_pf >= 1.5 else (MANIM_YELLOW if overall_train_pf >= 1.0 else MANIM_RED)
        test_pf_color = MANIM_GREEN if overall_test_pf >= 1.5 else (MANIM_YELLOW if overall_test_pf >= 1.0 else MANIM_RED)
        
        overall_row = VGroup(
            styled_text("Avg Train PF", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{overall_train_pf:.2f}", size=SZ_VALUE, color=train_pf_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        test_row = VGroup(
            styled_text("Avg Test PF", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{overall_test_pf:.2f}", size=SZ_VALUE, color=test_pf_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        # OOS/IS ratio
        ratio_color = MANIM_GREEN if avg_ratio >= 0.8 else (MANIM_YELLOW if avg_ratio >= 0.6 else MANIM_RED)
        ratio_row = VGroup(
            styled_text("OOS/IS Ratio", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{avg_ratio:.2f}", size=SZ_VALUE, color=ratio_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        # Degradation slope
        slope_color = MANIM_RED if slope < -0.05 else (MANIM_YELLOW if slope < 0 else MANIM_GREEN)
        slope_row = VGroup(
            styled_text("Slope", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{slope:.4f}", size=SZ_VALUE, color=slope_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        # Final window comparison
        final_train_color = MANIM_GREEN if final_train_pf >= 1.5 else MANIM_RED
        final_test_color = MANIM_GREEN if final_test_pf >= 1.5 else MANIM_RED
        final_row = VGroup(
            styled_text("Final Train/Test", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{final_train_pf:.2f}/{final_test_pf:.2f}", size=SZ_VALUE, color=MANIM_WHITE, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        stats_group = VGroup(overall_row, test_row, ratio_row, slope_row, final_row).arrange(DOWN, buff=0.15, aligned_edge=LEFT)
        stats_group.next_to(stats_title, DOWN, buff=0.3)
        stats_group.align_to(stats_title, LEFT)
        
        self.add(stats_title, stats_group)
        
        # Alert box if significant decay
        if is_decay_alert:
            alert_box = RoundedRectangle(
                width=2.5,
                height=0.6,
                corner_radius=0.1,
                fill_color=MANIM_RED,
                fill_opacity=0.2,
                stroke_color=MANIM_RED,
                stroke_width=1,
            ).next_to(stats_group, DOWN, buff=0.4).align_to(stats_title, LEFT)
            
            alert_text = styled_text("⚠ DECAY ALERT", size=SZ_SMALL, color=MANIM_RED, weight="BOLD", font=FONT_SANS
            ).move_to(alert_box)
            
            ratio_text = mono_text(f"OOS/IS < 0.6", size=10, color=MANIM_RED
            ).next_to(alert_text, DOWN, buff=0.05)
            
            self.add(alert_box, alert_text, ratio_text)
        
        # Thin divider line
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)
        self.add(divider)
        
        # === RIGHT COLUMN: Chart ===
        chart_title = styled_text("PROFIT FACTOR BY WINDOW", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).shift(RIGHT * 1.0 + UP * 2.2)
        self.add(chart_title)
        
        n_windows = len(windows)
        
        # Y-axis range
        all_pfs = train_pfs + test_pfs
        y_min = max(0, min(all_pfs) * 0.8)
        y_max = max(all_pfs) * 1.2
        
        axes = Axes(
            x_range=[0, n_windows - 1, max(1, (n_windows - 1) // 5)],
            y_range=[y_min, y_max, (y_max - y_min) / 5],
            x_length=8.0,
            y_length=4.0,
            axis_config={"include_tip": False, "font_size": 14},
        ).shift(RIGHT * 0.8 + DOWN * 0.3)
        
        # X-axis label
        x_label = styled_text("Window", size=SZ_LABEL, font=FONT_SANS).next_to(axes.x_axis, DOWN, buff=0.1)
        # Y-axis label
        y_label = styled_text("Profit Factor", size=SZ_LABEL, font=FONT_SANS).next_to(axes.y_axis, LEFT, buff=0.1).rotate(90 * DEGREES)
        
        self.add(axes, x_label, y_label)
        
        # Reference line at PF=1
        if y_min <= 1 <= y_max:
            ref_line = DashedLine(
                axes.c2p(0, 1),
                axes.c2p(n_windows - 1, 1),
                color=MANIM_GREY,
                stroke_opacity=0.5,
            )
            ref_text = mono_text("PF=1", size=10, color=MANIM_GREY).next_to(ref_line, RIGHT, buff=0.05)
            self.add(ref_line, ref_text)
        
        # Train PF line
        train_points = [axes.c2p(i, train_pfs[i]) for i in range(n_windows)]
        train_line = VMobject(color=MANIM_BLUE, stroke_width=2.5)
        train_line.set_points_smoothly(train_points)
        
        # Test PF line
        test_points = [axes.c2p(i, test_pfs[i]) for i in range(n_windows)]
        test_line = VMobject(color=MANIM_GREEN, stroke_width=2.5)
        test_line.set_points_smoothly(test_points)
        
        self.add(train_line, test_line)
        
        # Data points with hover values
        for i in range(n_windows):
            # Train dot
            train_dot = Dot(axes.c2p(i, train_pfs[i]), radius=0.05, color=MANIM_BLUE)
            
            # Test dot
            test_dot = Dot(axes.c2p(i, test_pfs[i]), radius=0.05, color=MANIM_GREEN)
            
            # Value labels
            train_label = mono_text(f"{train_pfs[i]:.1f}", size=8, color=MANIM_BLUE
            ).next_to(train_dot, UP, buff=0.05)
            
            test_label = mono_text(f"{test_pfs[i]:.1f}", size=8, color=MANIM_GREEN
            ).next_to(test_dot, DOWN, buff=0.05)
            
            self.add(train_dot, test_dot, train_label, test_label)
        
        # Trend line (regression)
        x_vals = np.arange(n_windows)
        if np.std(train_pfs) > 0 and n_windows > 1:
            # Train trend
            train_coef = np.polyfit(x_vals, train_pfs, 1)
            train_trend_y = np.polyval(train_coef, [0, n_windows - 1])
            train_trend = Line(
                axes.c2p(0, train_trend_y[0]),
                axes.c2p(n_windows - 1, train_trend_y[1]),
                color=MANIM_BLUE,
                stroke_opacity=0.5,
                stroke_width=1,
            )
            
            # Test trend
            test_coef = np.polyfit(x_vals, test_pfs, 1)
            test_trend_y = np.polyval(test_coef, [0, n_windows - 1])
            test_trend = Line(
                axes.c2p(0, test_trend_y[0]),
                axes.c2p(n_windows - 1, test_trend_y[1]),
                color=MANIM_GREEN,
                stroke_opacity=0.5,
                stroke_width=1,
            )
            
            self.add(train_trend, test_trend)
        
        # Legend
        legend_items = [
            (MANIM_BLUE, "Train PF"),
            (MANIM_GREEN, "Test PF"),
        ]
        for i, (color, label) in enumerate(legend_items):
            legend_dot = Dot(color=color, radius=0.05).move_to(RIGHT * 3.5 + UP * (1.5 - i * 0.25))
            legend_text = styled_text(label, size=10, color=MANIM_GREY, font=FONT_SANS
            ).next_to(legend_dot, RIGHT, buff=0.1)
            self.add(legend_dot, legend_text)
        
        # Footer
        footer = styled_text("IG-88 · Walk-Forward Analysis · H3-E v2", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).to_edge(DOWN, buff=0.1)
        self.add(footer)
        
        self.wait(1)
