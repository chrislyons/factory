"""
Correlation Matrix Scene — 25/75 layout.
Shows 12x12 rolling correlation heatmap with diversification score.
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
from viz.data_loader import load_ohlcv

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12

# 12 pairs from friction_tracker.py
PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']


def compute_rolling_correlation(prices_dict, window=30):
    """
    Compute rolling correlation matrix for all pairs.
    Returns correlation matrix for the last window period.
    """
    pairs = list(prices_dict.keys())
    n_pairs = len(pairs)
    
    # Ensure all series have same length
    min_len = min(len(prices_dict[p]) for p in pairs)
    if min_len < window:
        window = min_len
    
    # Get last window prices
    recent_prices = {}
    for p in pairs:
        recent_prices[p] = prices_dict[p][-window:]
    
    # Compute correlation matrix
    corr_matrix = np.zeros((n_pairs, n_pairs))
    for i, p1 in enumerate(pairs):
        for j, p2 in enumerate(pairs):
            if i == j:
                corr_matrix[i, j] = 1.0
            else:
                # Simple Pearson correlation
                x = recent_prices[p1]
                y = recent_prices[p2]
                x_mean = np.mean(x)
                y_mean = np.mean(y)
                x_std = np.std(x)
                y_std = np.std(y)
                if x_std > 0 and y_std > 0:
                    corr = np.mean((x - x_mean) * (y - y_mean)) / (x_std * y_std)
                    corr_matrix[i, j] = corr
                else:
                    corr_matrix[i, j] = 0.0
    
    return corr_matrix


def compute_diversification_score(corr_matrix):
    """
    Compute effective diversification score.
    Lower correlation = higher diversification.
    Score: 0-100 (100 = perfect diversification).
    """
    n = corr_matrix.shape[0]
    
    # Average off-diagonal correlation
    off_diag_sum = 0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            off_diag_sum += abs(corr_matrix[i, j])
            count += 1
    
    avg_corr = off_diag_sum / count if count > 0 else 0
    
    # Convert to diversification score
    # If avg correlation is 1.0, diversification is 0
    # If avg correlation is 0.0, diversification is 100
    div_score = (1.0 - avg_corr) * 100
    
    return div_score, avg_corr


def corr_color(corr_value):
    """Map correlation value to color."""
    # Red for high positive correlation, blue for negative, grey for neutral
    if corr_value >= 0.7:
        return '#ef4444'  # Red
    elif corr_value >= 0.3:
        return '#f59e0b'  # Yellow
    elif corr_value <= -0.3:
        return '#3b82f6'  # Blue
    else:
        return '#71717a'  # Grey


class CorrelationMatrixScene(Scene):
    def construct(self):
        """
        Render correlation matrix heatmap.
        Left: Diversification stats.
        Right: 12x12 correlation heatmap.
        """
        self.camera.background_color = "#09090b"
        
        # Load price data for all pairs
        prices_dict = {}
        for pair in PAIRS:
            data = load_ohlcv(pair)
            if data is not None:
                prices_dict[pair] = data['close']
            else:
                # Generate synthetic prices
                n_bars = 200
                rng = np.random.default_rng(hash(pair) % 10000)
                base_price = 100 + rng.random() * 50
                # Add some correlation with BTC-like movement
                btc_movement = rng.standard_normal(n_bars) * 2
                prices_dict[pair] = base_price + np.cumsum(btc_movement + rng.standard_normal(n_bars) * 1.5)
        
        # Compute correlation matrix
        corr_matrix = compute_rolling_correlation(prices_dict, window=30)
        
        # Compute diversification metrics
        div_score, avg_corr = compute_diversification_score(corr_matrix)
        
        # Count high correlation pairs
        high_corr_pairs = []
        n = len(PAIRS)
        for i in range(n):
            for j in range(i + 1, n):
                if corr_matrix[i, j] >= 0.7:
                    high_corr_pairs.append((PAIRS[i], PAIRS[j], corr_matrix[i, j]))
        
        # === TITLE ===
        title = header_text("CORRELATION MATRIX", size=SZ_TITLE).to_edge(UP, buff=0.15)
        self.add(title)
        
        # === LEFT COLUMN: Stats ===
        stats_title = styled_text("DIVERSIFICATION", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.6)
        
        # Diversification score with color
        div_color = MANIM_GREEN if div_score >= 60 else (MANIM_YELLOW if div_score >= 40 else MANIM_RED)
        div_row = VGroup(
            styled_text("Score", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{div_score:.1f}", size=SZ_VALUE, color=div_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        # Average correlation
        avg_corr_color = MANIM_RED if avg_corr >= 0.5 else (MANIM_YELLOW if avg_corr >= 0.3 else MANIM_GREEN)
        avg_row = VGroup(
            styled_text("Avg Corr", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{avg_corr:.3f}", size=SZ_VALUE, color=avg_corr_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        # High correlation count
        high_corr_color = MANIM_RED if len(high_corr_pairs) > 5 else (MANIM_YELLOW if len(high_corr_pairs) > 2 else MANIM_GREEN)
        high_row = VGroup(
            styled_text("High Corr", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
            mono_text(f"{len(high_corr_pairs)} pairs", size=SZ_VALUE, color=high_corr_color, weight="BOLD"),
        ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        
        stats_group = VGroup(div_row, avg_row, high_row).arrange(DOWN, buff=0.2, aligned_edge=LEFT)
        stats_group.next_to(stats_title, DOWN, buff=0.3)
        stats_group.align_to(stats_title, LEFT)
        
        self.add(stats_title, stats_group)
        
        # High correlation pairs list
        if high_corr_pairs:
            high_corr_title = styled_text("HIGH CORRELATION (>0.7)", size=SZ_SMALL, color=MANIM_RED, weight="BOLD", font=FONT_SANS
            ).next_to(stats_group, DOWN, buff=0.4).align_to(stats_title, LEFT)
            self.add(high_corr_title)
            
            for i, (p1, p2, corr) in enumerate(high_corr_pairs[:5]):  # Show top 5
                pair_row = VGroup(
                    styled_text(f"{p1}-{p2}", size=10, color=MANIM_WHITE, font=FONT_SANS),
                    mono_text(f"{corr:.2f}", size=10, color=MANIM_RED),
                ).arrange(RIGHT, buff=0.2)
                pair_row.next_to(high_corr_title, DOWN, buff=0.1 + i * 0.2)
                pair_row.align_to(high_corr_title, LEFT)
                self.add(pair_row)
        
        # Thin divider line
        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)
        self.add(divider)
        
        # === RIGHT COLUMN: Heatmap ===
        heatmap_title = styled_text("30-DAY ROLLING CORRELATION", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).shift(RIGHT * 1.0 + UP * 2.2)
        self.add(heatmap_title)
        
        # Create heatmap
        n = len(PAIRS)
        cell_size = 0.45
        heatmap_group = VGroup()
        
        # Start position (centered in right area)
        start_x = 0.5
        start_y = 1.5
        
        # Draw cells
        for i in range(n):
            for j in range(n):
                corr_val = corr_matrix[i, j]
                color = corr_color(corr_val)
                opacity = 0.3 + abs(corr_val) * 0.7  # Higher correlation = more opaque
                
                cell = Square(
                    side_length=cell_size,
                    fill_color=color,
                    fill_opacity=opacity,
                    stroke_color=MANIM_GREY,
                    stroke_width=0.5,
                    stroke_opacity=0.3,
                )
                cell.move_to(RIGHT * (start_x + j * cell_size) + UP * (start_y - i * cell_size))
                
                # Add correlation value for high correlations
                if abs(corr_val) >= 0.5 and i != j:
                    corr_text = mono_text(f"{corr_val:.1f}", size=8, color=MANIM_WHITE)
                    corr_text.move_to(cell)
                    heatmap_group.add(cell, corr_text)
                else:
                    heatmap_group.add(cell)
        
        # Add pair labels
        for i, pair in enumerate(PAIRS):
            # Row labels (left side)
            row_label = styled_text(pair[:3], size=8, color=MANIM_GREY, font=FONT_SANS)
            row_label.move_to(RIGHT * (start_x - cell_size) + UP * (start_y - i * cell_size))
            
            # Column labels (top)
            col_label = styled_text(pair[:3], size=8, color=MANIM_GREY, font=FONT_SANS)
            col_label.move_to(RIGHT * (start_x + i * cell_size) + UP * (start_y + cell_size))
            col_label.rotate(45 * DEGREES)
            
            heatmap_group.add(row_label, col_label)
        
        self.add(heatmap_group)
        
        # Color legend
        legend_y = start_y - n * cell_size - 0.3
        legend_items = [
            (0.7, "≥0.7", '#ef4444'),
            (0.3, "0.3-0.7", '#f59e0b'),
            (0.0, "0-0.3", '#71717a'),
            (-0.3, "-0.3-0", '#71717a'),
            (-0.7, "≤-0.7", '#3b82f6'),
        ]
        
        for i, (corr_val, label, color) in enumerate(legend_items):
            legend_dot = Square(side_length=0.15, fill_color=color, fill_opacity=0.8, stroke_width=0
            ).move_to(RIGHT * (start_x + i * 0.8) + UP * legend_y)
            legend_text = styled_text(label, size=8, color=MANIM_GREY, font=FONT_SANS
            ).next_to(legend_dot, DOWN, buff=0.05)
            self.add(legend_dot, legend_text)
        
        # Footer
        footer = styled_text("IG-88 · Correlation Analysis · 12 Pairs", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).to_edge(DOWN, buff=0.1)
        self.add(footer)
        
        self.wait(1)
