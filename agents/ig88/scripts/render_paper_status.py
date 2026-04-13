#!/usr/bin/env python3
"""
Render Paper Trading Status Visualization
==========================================
Generates a compact GIF of current paper trading status.
Run after each scan cycle for Matrix posting.

Usage:
  python3 scripts/render_paper_status.py [--output path.gif]
"""
import sys
import argparse
import subprocess
from pathlib import Path

MANIM_CLI = "/opt/homebrew/Cellar/manim/0.20.1/libexec/bin/manim"
PROJECT_ROOT = Path(__file__).parents[1]
VIZ_DIR = PROJECT_ROOT / "src" / "viz"
RENDER_DIR = PROJECT_ROOT / "renders"

def render_paper_status(output_path=None):
    """Render paper trading status scene and convert to compact GIF."""
    
    scene_file = VIZ_DIR / "paper_trading.py"
    
    # Step 1: Render with Manim
    cmd = [
        MANIM_CLI, "render",
        str(scene_file), "PaperTradingScene",
        "-ql",  # Low quality for speed
        "--media_dir", str(RENDER_DIR),
        "--format", "gif"
    ]
    
    print("Rendering PaperTradingScene...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    
    if result.returncode != 0:
        print(f"Manim render failed: {result.returncode}")
        return None
    
    # Step 2: Find generated GIF and convert to compact version
    gif_dir = RENDER_DIR / "videos" / "paper_trading" / "480p15"
    generated_gifs = list(gif_dir.glob("PaperTradingScene*.gif"))
    
    if not generated_gifs:
        print("No GIF found after render")
        return None
    
    source_gif = generated_gifs[0]
    
    if output_path is None:
        output_path = RENDER_DIR / "paper_trading_status.gif"
    else:
        output_path = Path(output_path)
    
    # Step 3: Convert to compact GIF (lower fps, smaller size)
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(source_gif),
        "-vf", "fps=8,scale=640:-1:flags=lanczos",
        "-loop", "0",
        str(output_path)
    ]
    
    print("Converting to compact GIF...")
    subprocess.run(ffmpeg_cmd, capture_output=True)
    
    size_kb = output_path.stat().st_size / 1024
    print(f"\nOutput: {output_path}")
    print(f"Size: {size_kb:.0f}KB")
    
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Render paper trading status")
    parser.add_argument("--output", "-o", default=None, help="Output GIF path")
    args = parser.parse_args()
    
    result = render_paper_status(args.output)
    if result:
        print("Done!")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
