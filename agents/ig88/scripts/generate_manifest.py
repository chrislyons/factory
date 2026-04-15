#!/usr/bin/env python3
"""
generate_manifest.py - Scan renders/videos/*/1080p60/*.gif and output manifest.json

Outputs renders/manifest.json with scene metadata for the viewer.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_scene_category(scene_name: str) -> str:
    """Map scene names to filter categories."""
    category_map = {
        "EquityCurveScene": "equity",
        "IchimokuCloudScene": "ichimoku",
        "BacktestComparisonScene": "backtest",
        "MRValidationScene": "mr",
        "DailySummaryScene": "daily",
        "PaperTradingScene": "paper",
    }
    return category_map.get(scene_name, "other")


def get_scene_title(scene_name: str) -> str:
    """Map scene names to display titles."""
    title_map = {
        "EquityCurveScene": "Equity Curve — H3-Combined Backtest",
        "IchimokuCloudScene": "Ichimoku Cloud — H3-A",
        "BacktestComparisonScene": "Walk-Forward Validation",
        "MRValidationScene": "Mean Reversion Validation",
        "DailySummaryScene": "Daily Summary",
        "PaperTradingScene": "Paper Trading Status",
    }
    return title_map.get(scene_name, scene_name)


def get_badge_type(scene_name: str) -> dict:
    """Get badge label and color class for scene."""
    badge_map = {
        "EquityCurveScene": ("Backtest", "green"),
        "IchimokuCloudScene": ("Signal", "blue"),
        "BacktestComparisonScene": ("OOS", "yellow"),
        "MRValidationScene": ("Strategy", "green"),
        "DailySummaryScene": ("Report", "green"),
        "PaperTradingScene": ("Live", "blue"),
    }
    label, color = badge_map.get(scene_name, ("Render", "blue"))
    return {"label": label, "color": color}


def scan_renders(renders_dir: Path) -> list:
    """Scan for 1080p60 GIF files and collect metadata."""
    videos_dir = renders_dir / "videos"
    if not videos_dir.exists():
        print(f"Warning: {videos_dir} not found", file=sys.stderr)
        return []

    renders = []

    for scene_dir in videos_dir.iterdir():
        if not scene_dir.is_dir():
            continue

        gif_1080 = scene_dir / "1080p60"
        if not gif_1080.exists():
            continue

        for gif_file in gif_1080.glob("*.gif"):
            if gif_file.name.startswith("."):
                continue

            stat = gif_file.stat()
            scene_name = gif_file.stem  # filename without extension
            category = get_scene_category(scene_name)

            renders.append({
                "scene_name": scene_name,
                "title": get_scene_title(scene_name),
                "category": category,
                "path": str(gif_file.relative_to(renders_dir)),
                "path_480": str((scene_dir / "480p15" / gif_file.name).relative_to(renders_dir)),
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "mtime_unix": int(stat.st_mtime),
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "badge": get_badge_type(scene_name),
            })

    # Sort by mtime descending (newest first)
    renders.sort(key=lambda x: x["mtime_unix"], reverse=True)

    return renders


def main():
    script_dir = Path(__file__).resolve().parent
    renders_dir = script_dir.parent  # renders/scripts/... -> renders/

    # Allow override via argument
    if len(sys.argv) > 1:
        renders_dir = Path(sys.argv[1])

    renders = scan_renders(renders_dir)

    manifest = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "renders_dir": str(renders_dir),
        "total_renders": len(renders),
        "scenes": renders,
    }

    output_path = renders_dir / "manifest.json"
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {output_path} with {len(renders)} scenes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
