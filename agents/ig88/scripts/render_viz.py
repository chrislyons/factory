#!/usr/bin/env python3
"""
IG-88 Visualization Render Helper
==================================
Renders Manim scenes with IG-88 data paths configured.

Usage:
  python3 scripts/render_viz.py equity        # Equity curve (sample data)
  python3 scripts/render_viz.py ichimoku      # Ichimoku cloud animation
  python3 scripts/render_viz.py comparison    # Train vs Test comparison
  python3 scripts/render_viz.py daily         # Daily summary GIF
  
  python3 scripts/render_viz.py equity --quality h  # High quality
  python3 scripts/render_viz.py daily --format gif  # GIF for Matrix
"""

import sys
import argparse
from pathlib import Path

MANIM_PYTHON = "/opt/homebrew/Cellar/manim/0.20.1/libexec/bin/python3"
MANIM_CLI = "/opt/homebrew/Cellar/manim/0.20.1/libexec/bin/manim"
PROJECT_ROOT = Path(__file__).parents[1]
VIZ_DIR = PROJECT_ROOT / "src" / "viz"
RENDER_DIR = PROJECT_ROOT / "renders"

SCENES = {
    "equity": ("equity_curve.py", "EquityCurveScene"),
    "ichimoku": ("ichimoku_cloud.py", "IchimokuCloudScene"),
    "comparison": ("backtest_comparison.py", "BacktestComparisonScene"),
    "daily": ("daily_summary.py", "DailySummaryScene"),
    "paper": ("paper_trading.py", "PaperTradingScene"),
    "mr": ("mr_validation.py", "MRValidationScene"),
    "mr_config": ("mr_validation.py", "MRConfigComparisonScene"),
    "mr_regime": ("mr_validation.py", "MRRegimeScene"),
}


def render(scene_name: str, quality: str = "l", fmt: str = "video"):
    """Render a scene."""
    if scene_name not in SCENES:
        print(f"Unknown scene: {scene_name}")
        print(f"Available: {', '.join(SCENES.keys())}")
        sys.exit(1)
    
    file_name, class_name = SCENES[scene_name]
    scene_path = VIZ_DIR / file_name
    
    # Quality flags
    quality_flags = {
        "l": "-ql",   # 480p 15fps
        "m": "-qm",   # 720p 30fps
        "h": "-qh",   # 1080p 60fps
        "k": "-qk",   # 4K
    }
    
    # Format flags
    if fmt == "gif":
        format_flag = "--format"
        format_value = "gif"
    else:
        format_flag = None
        format_value = None
    
    q_flag = quality_flags.get(quality, "-ql")
    
    cmd = [
        MANIM_CLI,
        "render",
        str(scene_path),
        class_name,
        q_flag,
        "--media_dir", str(RENDER_DIR),
    ]
    
    if format_flag:
        cmd.extend([format_flag, format_value])
    
    print(f"Rendering {class_name}...")
    print(f"Command: {' '.join(cmd)}")
    
    import subprocess
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    
    if result.returncode == 0:
        print(f"\nRender complete! Output in {RENDER_DIR}/")
    else:
        print(f"\nRender failed with code {result.returncode}")
    
    return result.returncode


def list_scenes():
    """List available scenes."""
    print("Available scenes:")
    for name, (file, cls) in SCENES.items():
        print(f"  {name:12} → {cls} ({file})")


def main():
    parser = argparse.ArgumentParser(description="IG-88 Visualization Renderer")
    parser.add_argument("scene", nargs="?", default=None, help="Scene to render")
    parser.add_argument("--quality", "-q", choices=["l", "m", "h", "k"], default="l", help="Quality level")
    parser.add_argument("--format", "-f", choices=["mp4", "gif"], default="mp4", help="Output format")
    parser.add_argument("--list", "-l", action="store_true", help="List available scenes")
    
    args = parser.parse_args()
    
    if args.list:
        list_scenes()
        return
    
    if args.scene is None:
        print("Usage: python3 scripts/render_viz.py <scene> [--quality l/m/h/k] [--format mp4/gif]")
        print()
        list_scenes()
        sys.exit(1)
    
    render(args.scene, args.quality, args.format)


if __name__ == "__main__":
    main()
