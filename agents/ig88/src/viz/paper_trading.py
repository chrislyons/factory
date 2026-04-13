"""
Paper Trading Status — Live portfolio monitoring visualization.
Reads from state/paper_trading/portfolio.json.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[1]))

import json
import numpy as np
from datetime import datetime, timezone
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

STATE_FILE = Path(__file__).parents[2] / "state" / "paper_trading" / "portfolio.json"


def load_paper_trading_state():
    """Load paper trading state from JSON."""
    if not STATE_FILE.exists():
        return None
    with open(STATE_FILE) as f:
        return json.load(f)


class PaperTradingScene(Scene):
    def construct(self):
        self.camera.background_color = "#09090b"
        
        state = load_paper_trading_state()
        
        if state is None:
            self._show_no_data()
            return
        
        stats = state.get("stats", {})
        positions = state.get("positions", {})
        trades = state.get("completed_trades", [])
        last_update = state.get("last_update", "Unknown")
        
        # Parse timestamp
        try:
            dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        except:
            date_str = last_update[:19]
        
        # TITLE
        header = header_text("IG-88 PAPER TRADING", size=SZ_TITLE).to_edge(UP, buff=0.15)
        date_sub = styled_text(date_str, size=SZ_SMALL, color=MANIM_GREY, font=FONT_MONO).next_to(header, DOWN, buff=0.02)
        self.add(header, date_sub)
        
        # === LEFT COLUMN: Stats ===
        stats_title = styled_text("PERFORMANCE", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).to_corner(UL, buff=0.3).shift(DOWN * 0.9)
        
        total_pnl = stats.get("total_pnl", 0)
        win_rate = stats.get("win_rate", 0)
        profit_factor = stats.get("profit_factor", 0)
        total_trades = stats.get("total_trades", 0)
        winning = stats.get("winning_trades", 0)
        losing = stats.get("losing_trades", 0)
        
        pnl_color = MANIM_GREEN if total_pnl >= 0 else MANIM_RED
        wr_color = MANIM_GREEN if win_rate >= 50 else MANIM_RED
        pf_color = MANIM_GREEN if profit_factor >= 1.5 else (MANIM_YELLOW if profit_factor >= 1.0 else MANIM_RED)
        
        left_stats = VGroup()
        for label, value, color in [
            ("Scans", str(stats.get("scan_count", 0)), MANIM_WHITE),
            ("Trades", str(total_trades), MANIM_WHITE),
            ("W / L", f"{winning} / {losing}", MANIM_WHITE),
            ("Win Rate", f"{win_rate:.1f}%", wr_color),
            ("Total PnL", f"{total_pnl:+.3f}%", pnl_color),
            ("Profit Factor", f"{profit_factor:.2f}", pf_color),
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
        
        # === RIGHT COLUMN: Positions ===
        pos_title = styled_text("OPEN POSITIONS", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
        ).shift(RIGHT * 1.0 + UP * 2.2)
        self.add(pos_title)
        
        if positions:
            # Column headers
            col_headers = VGroup(
                styled_text("PAIR", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("TIER", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("ENTRY", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("STOP", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("TARGET", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("BARS", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            ).arrange(RIGHT, buff=0.35).next_to(pos_title, DOWN, buff=0.15)
            col_headers[0].align_to(pos_title, LEFT)
            self.add(col_headers)
            
            for i, (pair, pos) in enumerate(positions.items()):
                entry = pos.get("entry_price", 0)
                atr = pos.get("atr", 0)
                stop_mult = pos.get("stop_mult", 1)
                target_mult = pos.get("target_mult", 2)
                
                stop_price = entry - atr * stop_mult
                target_price = entry + atr * target_mult
                bars_held = pos.get("bars_held", 0)
                tier = pos.get("tier", "?")
                
                tier_color = {
                    "STRONG": MANIM_GREEN,
                    "MEDIUM": MANIM_YELLOW,
                    "WEAK": MANIM_BLUE,
                }.get(tier, MANIM_WHITE)
                
                row = VGroup(
                    mono_text(pair, size=SZ_LABEL, color=MANIM_WHITE, weight="BOLD"),
                    styled_text(tier, size=SZ_SMALL, color=tier_color, font=FONT_SANS),
                    mono_text(f"{entry:.4f}", size=SZ_SMALL, color=MANIM_GREY),
                    mono_text(f"{stop_price:.4f}", size=SZ_SMALL, color=MANIM_RED),
                    mono_text(f"{target_price:.4f}", size=SZ_SMALL, color=MANIM_GREEN),
                    mono_text(f"{bars_held}", size=SZ_SMALL, color=MANIM_WHITE),
                ).arrange(RIGHT, buff=0.35)
                
                row[0].align_to(col_headers[0], LEFT)
                row[1].align_to(col_headers[1], LEFT)
                row[2].align_to(col_headers[2], LEFT)
                row[3].align_to(col_headers[3], LEFT)
                row[4].align_to(col_headers[4], LEFT)
                row[5].align_to(col_headers[5], LEFT)
                row.next_to(col_headers, DOWN, buff=0.08 + i * 0.45)
                
                # Row background
                bg = BackgroundRectangle(
                    row, fill_color=MANIM_WHITE, fill_opacity=0.02,
                    buff=0.06, corner_radius=0.02,
                )
                self.add(bg, row)
        else:
            no_pos_text = styled_text("No open positions", size=SZ_LABEL, color=MANIM_GREY, font=FONT_SANS
            ).next_to(pos_title, DOWN, buff=0.5)
            self.add(no_pos_text)
            
            # Show scan info
            scan_info = VGroup(
                styled_text("Scanning 12 pairs every 4h", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("Entry: RSI + Bollinger Bands + Volume", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
                styled_text("Venue: Kraken (limit orders, 1% friction)", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS),
            ).arrange(DOWN, aligned_edge=LEFT, buff=0.08).next_to(no_pos_text, DOWN, buff=0.4)
            self.add(scan_info)
        
        # === Recent Trades (if any) ===
        if trades:
            trades_title = styled_text("RECENT TRADES", size=SZ_SECTION, color=MANIM_YELLOW, weight="BOLD", font=FONT_SANS
            ).shift(RIGHT * 1.0 + DOWN * 0.2)
            self.add(trades_title)
            
            # Show last 5 trades
            recent = trades[-5:] if len(trades) > 5 else trades
            
            for i, trade in enumerate(recent):
                pnl = trade.get("pnl_pct", 0)
                pair = trade.get("pair", "?")
                reason = trade.get("exit_reason", "?")
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
        footer = styled_text("IG-88 \u00b7 Paper Trading \u00b7 Kraken Spot", size=SZ_SMALL, color=MANIM_GREY, font=FONT_SANS
        ).to_edge(DOWN, buff=0.1)
        self.add(footer)
        
        self.wait(1)
    
    def _show_no_data(self):
        """Show placeholder when no data available."""
        header = header_text("IG-88 PAPER TRADING", size=SZ_TITLE).to_edge(UP, buff=0.15)
        no_data = styled_text("No paper trading data found", size=SZ_SECTION, color=MANIM_RED, font=FONT_SANS
        ).move_to(ORIGIN)
        hint = styled_text("Run paper_scan.py to initialize", size=SZ_LABEL, color=MANIM_GREY, font=FONT_MONO
        ).next_to(no_data, DOWN, buff=0.3)
        
        self.add(header, no_data, hint)
        self.wait(1)
