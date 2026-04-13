"""
Daily Summary — 25/75 layout, left-aligned left column.
Loads real paper trading state when available.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

from datetime import datetime, timezone
from manim import *
from viz.theme import (
    FONT_SANS, FONT_MONO, MANIM_GREEN, MANIM_RED, MANIM_BLUE,
    MANIM_YELLOW, MANIM_GREY, MANIM_WHITE, REGIME_COLORS,
    header_text, mono_text, styled_text,
)
from viz.data_loader import load_paper_trading_state, load_regime_state

SZ_TITLE = 22
SZ_SECTION = 16
SZ_LABEL = 14
SZ_VALUE = 16
SZ_SMALL = 12


class DailySummaryScene(Scene):
    def construct(self, date=None, trades=None, regime=None, open_positions=None, stats=None):
        """
        Render daily summary from paper trading state.
        
        Args:
            date: Date string (None = auto from state)
            trades: List of trades (None = load from state)
            regime: Regime string (None = load from current_regime.json)
            open_positions: List of positions (None = load from state)
            stats: Stats dict (None = load from state)
        """
        self.camera.background_color = "#09090b"
        
        # Load real data if not provided
        if stats is None or trades is None or open_positions is None:
            state = load_paper_trading_state()
            loaded_stats = state.get("stats", {})
            loaded_positions = state.get("positions", {})
            loaded_trades = state.get("completed_trades", [])
            last_update = state.get("last_update", "Unknown")
            
            if stats is None:
                stats = loaded_stats
            if trades is None:
                trades = loaded_trades
            if open_positions is None:
                # Convert positions dict to list format
                open_positions = []
                for pair, pos in loaded_positions.items():
                    open_positions.append({
                        "symbol": pair,
                        "strategy": pos.get("strategy", "MR"),
                        "unrealized": pos.get("unrealized_pnl", 0),
                        "bars_held": pos.get("bars_held", 0),
                    })
            
            if date is None:
                try:
                    dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
                    date = dt.strftime("%Y-%m-%d")
                except:
                    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Load regime
        if regime is None:
            regime_state = load_regime_state()
            regime = regime_state.get("state", "UNKNOWN")
        
        # Default values if still None
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if trades is None:
            trades = []
        if open_positions is None:
            open_positions = []
        if stats is None:
            stats = {
                "scan_count": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "profit_factor": 0,
            }
        
        # Compute derived stats
        wins = stats.get("winning_trades", sum(1 for t in trades if t.get("type") == "win"))
        losses = stats.get("losing_trades", len(trades) - wins)
        total_pnl = stats.get("total_pnl", sum(t.get("pnl_pct", 0) for t in trades))
        win_rate = stats.get("win_rate", wins / len(trades) * 100 if trades else 0)
        
        # TITLE with regime badge
        header = header_text("IG-88 DAILY SUMMARY", size=SZ_TITLE).to_edge(UP, buff=0.15)
        date_sub = styled_text(date, size=SZ_SMALL, color=MANIM_GREY, font=FONT_MONO).next_to(header, DOWN, buff=0.02)
        
        regime_color = REGIME_COLORS.get(regime, MANIM_GREY)
        regime_dot = Circle(radius=0.08, color=regime_color, fill_color=regime_color, fill_opacity=1)
        regime_txt = mono_text(regime, size=SZ_SMALL, color=regime_color, weight="BOLD")
        regime_group = VGroup(regime_dot, regime_txt).arrange(RIGHT, buff=0.06).to_corner(UR, buff=0.3).shift(DOWN * 0.3)
        
        self.add(header, date_sub, regime_group)

        # === LEFT COLUMN: Stats ===
        stats_title = styled_text("STATISTICS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.9)

        pnl_color = MANIM_GREEN if total_pnl >= 0 else MANIM_RED
        wr_color = MANIM_GREEN if win_rate >= 50 else MANIM_RED
        pf = stats.get("profit_factor", 0)
        pf_color = MANIM_GREEN if pf >= 1.5 else (MANIM_YELLOW if pf >= 1.0 else MANIM_RED)

        left_stats = VGroup()
        for label, value, color in [
            ("Scans", str(stats.get("scan_count", 0)), MANIM_WHITE),
            ("Trades", str(stats.get("total_trades", len(trades))), MANIM_WHITE),
            ("W / L", f"{wins} / {losses}", MANIM_WHITE),
            ("Win Rate", f"{win_rate:.1f}%", wr_color),
            ("Total PnL", f"{total_pnl:+.3f}%", pnl_color),
            ("Profit Factor", f"{pf:.2f}", pf_color),
        ]:
            row = VGroup(
                styled_text(label, size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS),
                mono_text(value, size=SZ_VALUE, color=color, weight="BOLD"),
            ).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
            left_stats.add(row)
        left_stats.arrange(DOWN, buff=0.14, aligned_edge=LEFT)
        left_stats.next_to(stats_title, DOWN, buff=0.2)
        left_stats.align_to(stats_title, LEFT)

        divider = Line(UP * 2.9, DOWN * 2.9, color=MANIM_GREY, stroke_opacity=0.15)
        divider.shift(RIGHT * -2.9)

        self.add(stats_title, left_stats, divider)

        # === RIGHT COLUMN: Open Positions ===
        pos_title = styled_text("OPEN POSITIONS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).shift(RIGHT * 1.0 + UP * 2.2)
        self.add(pos_title)

        if open_positions:
            # Column headers
            col_headers = VGroup(
                styled_text("SYM", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("STRAT", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("BARS", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("P&L", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            ).arrange(RIGHT, buff=0.8).next_to(pos_title, DOWN, buff=0.15)
            col_headers[0].align_to(pos_title, LEFT)
            self.add(col_headers)

            for i, pos in enumerate(open_positions):
                unrealized = pos.get("unrealized", 0)
                color = MANIM_GREEN if unrealized > 0 else MANIM_RED
                row = VGroup(
                    styled_text(pos.get("symbol", "?"), size=SZ_LABEL, color=MANIM_WHITE, weight="BOLD", font=FONT_SANS),
                    styled_text(pos.get("strategy", "MR"), size=SZ_SMALL, color=MANIM_BLUE, font=FONT_SANS),
                    mono_text(f"{pos.get('bars_held', 0)} bars", size=SZ_SMALL, color=MANIM_GREY),
                    mono_text(f"{unrealized:+.1f}%", size=SZ_LABEL, color=color, weight="BOLD"),
                )
                row.move_to(col_headers[0], aligned_edge=LEFT)
                row[1].move_to(col_headers[1], aligned_edge=LEFT)
                row[2].move_to(col_headers[2], aligned_edge=LEFT)
                row[3].move_to(col_headers[3], aligned_edge=LEFT)
                row.next_to(col_headers, DOWN, buff=0.08 + i * 0.45)
                
                bg = BackgroundRectangle(row, fill_color=MANIM_WHITE, fill_opacity=0.02, buff=0.06, corner_radius=0.02)
                self.add(bg, row)
        else:
            no_pos_text = styled_text("No open positions", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS
            ).next_to(pos_title, DOWN, buff=0.5)
            self.add(no_pos_text)
            
            scan_info = VGroup(
                styled_text("Scanning 12 pairs every 4h", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("Entry: RSI + Bollinger + Volume", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("Venue: Kraken (1% friction)", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            ).arrange(DOWN, aligned_edge=LEFT, buff=0.08).next_to(no_pos_text, DOWN, buff=0.4)
            self.add(scan_info)

        # Recent trades section
        if trades:
            trades_title = styled_text("RECENT TRADES", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
            ).shift(RIGHT * 1.0 + DOWN * 0.2)
            self.add(trades_title)
            
            recent = trades[-5:] if len(trades) > 5 else trades
            for i, trade in enumerate(recent):
                pnl = trade.get("pnl_pct", 0)
                pair = trade.get("pair", trade.get("symbol", "?"))
                reason = trade.get("exit_reason", trade.get("reason", "?"))
                color = MANIM_GREEN if pnl >= 0 else MANIM_RED
                
                trade_text = VGroup(
                    mono_text(pair, size=SZ_SMALL, color=MANIM_WHITE),
                    styled_text(reason, size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                    mono_text(f"{pnl:+.2f}%", size=SZ_SMALL, color=color, weight="BOLD"),
                ).arrange(RIGHT, buff=0.3)
                trade_text.next_to(trades_title, DOWN, buff=0.08 + i * 0.3)
                trade_text.align_to(trades_title, LEFT)
                self.add(trade_text)

        # Footer
        footer = styled_text("IG-88 · Paper Trading · Kraken Spot", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).to_edge(DOWN, buff=0.1)
        self.add(footer)

        self.wait(1)
