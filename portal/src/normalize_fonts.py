#!/usr/bin/env python3
"""
normalize_fonts.py — patch shared-fonts relative paths in synced HTML to /fonts/.

Idempotent. Skips files that already use /fonts/ or have no shared-fonts refs.
Must run post-rsync every sync (rsync restores originals).

Usage:
    python3 src/normalize_fonts.py [--repos-dir ./repos] [--dry-run] [--verbose]
    python3 src/normalize_fonts.py --file repos/blackbox/wireframes/architecture-gallery.html
"""

import argparse
import re
import sys
from pathlib import Path


# Matches any url('...shared-fonts/input/.../InputXxx-Variant.ttf')
# Handles all depth variants found in the corpus.
FONT_URL_RE = re.compile(
    r"url\(['\"](?:[^'\"]*shared-fonts/input/[^'\"]*/)"
    r"(Input(?:Sans|Mono|Serif)-[^/'\"]+\.ttf)['\"]\)",
    re.IGNORECASE,
)


def _replacement(match: re.Match) -> str:
    filename = match.group(1)
    return f"url('/fonts/{filename}')"


def normalize_file(html_path: Path, dry_run: bool = False) -> bool:
    """
    Patch font URL paths in html_path to use /fonts/.
    Returns True if the file was (or would be) modified.
    Skips files that are already normalised or have no shared-fonts refs.
    """
    try:
        original = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  ERROR reading {html_path}: {exc}", file=sys.stderr)
        return False

    patched, count = FONT_URL_RE.subn(_replacement, original)

    if count == 0:
        return False  # nothing to do

    if patched == original:
        return False  # already normalised (all refs already /fonts/)

    if not dry_run:
        try:
            html_path.write_text(patched, encoding="utf-8")
        except OSError as exc:
            print(f"  ERROR writing {html_path}: {exc}", file=sys.stderr)
            return False

    return True


def normalize_directory(
    repos_dir: Path, dry_run: bool = False, verbose: bool = False
) -> tuple[int, int, int]:
    """
    Walk repos_dir and normalize all *.html files.
    Returns (scanned, patched, errors).
    """
    scanned = 0
    patched = 0
    errors = 0

    if not repos_dir.is_dir():
        print(f"repos-dir not found: {repos_dir}", file=sys.stderr)
        return scanned, patched, errors

    for html_path in sorted(repos_dir.rglob("*.html")):
        scanned += 1
        try:
            modified = normalize_file(html_path, dry_run=dry_run)
            if modified:
                patched += 1
                if verbose:
                    tag = "[dry-run] would patch" if dry_run else "patched"
                    print(f"  {tag}: {html_path}")
        except Exception as exc:
            errors += 1
            print(f"  ERROR processing {html_path}: {exc}", file=sys.stderr)

    return scanned, patched, errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize shared-fonts paths in synced HTML files to /fonts/"
    )
    parser.add_argument("--repos-dir", default="./repos", help="Path to repos directory")
    parser.add_argument("--file", help="Normalize a single file instead of directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--verbose", action="store_true", help="Print each patched file")
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        modified = normalize_file(path, dry_run=args.dry_run)
        if modified:
            tag = "[dry-run] would patch" if args.dry_run else "Patched"
            print(f"{tag}: {path}")
        else:
            print(f"No changes: {path}")
        return

    repos_dir = Path(args.repos_dir)
    scanned, patched, errors = normalize_directory(repos_dir, dry_run=args.dry_run, verbose=args.verbose)

    mode = " (dry-run)" if args.dry_run else ""
    print(f"Scanned {scanned} files, patched {patched}{mode}, errors {errors}", file=sys.stderr)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
