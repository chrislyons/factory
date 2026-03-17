#!/usr/bin/env python3
"""
generate_index.py — scan repos/ directory and emit index.json manifest.

Usage:
    python3 src/generate_index.py [--repos-dir ./repos] [--output ./index.json] [--dry-run]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def extract_title(html_path: Path) -> str:
    """Extract <title> text from HTML, fallback to parent dir name. Max 80 chars."""
    try:
        content = html_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            return title[:80] if title else html_path.parent.parent.name
    except OSError:
        pass
    return html_path.parent.parent.name


def get_mtime_iso(path: Path) -> str:
    """Return file mtime as ISO 8601 UTC string."""
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_repo_files(repos_dir: Path) -> dict:
    """
    Walk repos_dir top-level subdirs. For each repo find:
      - gallery:  {repo}/wireframes/architecture-gallery.html
      - commands: {repo}/docs/repo-commands.html
    Returns dict of {repo_name: {"gallery": Path|None, "commands": Path|None}}
    """
    results = {}
    if not repos_dir.is_dir():
        return results

    for entry in sorted(repos_dir.iterdir()):
        if not entry.is_dir():
            continue
        repo_name = entry.name

        gallery = entry / "wireframes" / "architecture-gallery.html"
        commands = entry / "docs" / "repo-commands.html"

        results[repo_name] = {
            "gallery": gallery if gallery.is_file() else None,
            "commands": commands if commands.is_file() else None,
        }

    return results


def build_manifest(repos_dir: Path) -> list:
    """Build list of repo dicts with server-absolute paths."""
    repo_files = find_repo_files(repos_dir)
    manifest = []

    for name in sorted(repo_files.keys()):
        files = repo_files[name]
        gallery: Path | None = files["gallery"]
        commands: Path | None = files["commands"]

        # Skip repos with no recognised files
        if gallery is None and commands is None:
            continue

        entry = {
            "name": name,
            "gallery": f"/repos/{name}/wireframes/architecture-gallery.html" if gallery else None,
            "commands": f"/repos/{name}/docs/repo-commands.html" if commands else None,
            "gallery_title": extract_title(gallery) if gallery else None,
            "commands_title": extract_title(commands) if commands else None,
            "gallery_mtime": get_mtime_iso(gallery) if gallery else None,
            "commands_mtime": get_mtime_iso(commands) if commands else None,
        }
        manifest.append(entry)

    return manifest


STANDALONE_FILES = [
    {
        "name": "Local Inference Guide",
        "path": "standalone/local-inference-guide.html",
        "url": "/standalone/local-inference-guide.html",
    },
    {
        "name": "Credential Rotation Guide",
        "path": "standalone/credential-rotation-guide.html",
        "url": "/standalone/credential-rotation-guide.html",
    },
]


def build_standalone(base_dir: Path) -> list:
    """Build list of standalone file entries."""
    entries = []
    for item in STANDALONE_FILES:
        path = base_dir / item["path"]
        entry = {
            "name": item["name"],
            "url": item["url"],
            "mtime": get_mtime_iso(path) if path.is_file() else None,
        }
        entries.append(entry)
    return entries


def write_index(manifest: list, standalone: list, output_path: Path) -> None:
    """Write index.json to output_path."""
    data = {
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "explainers/src/generate_index.py",
        "version": "1",
        "count": len(manifest),
        "repos": manifest,
        "standalone": standalone,
    }
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate explainers index.json")
    parser.add_argument("--repos-dir", default="./repos", help="Path to repos directory")
    parser.add_argument("--output", default="./index.json", help="Output path for index.json")
    parser.add_argument("--dry-run", action="store_true", help="Print manifest without writing")
    args = parser.parse_args()

    repos_dir = Path(args.repos_dir)
    output_path = Path(args.output)
    base_dir = output_path.parent

    manifest = build_manifest(repos_dir)
    standalone = build_standalone(base_dir)

    if args.dry_run:
        data = {
            "generated_at": "(dry-run)",
            "generator": "explainers/src/generate_index.py",
            "version": "1",
            "count": len(manifest),
            "repos": manifest,
            "standalone": standalone,
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\n[dry-run] Would write {len(manifest)} repos to {output_path}", file=sys.stderr)
        return

    write_index(manifest, standalone, output_path)
    print(f"Wrote {len(manifest)} repos to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
