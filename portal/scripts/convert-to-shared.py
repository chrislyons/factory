#!/usr/bin/env python3
"""Convert gallery/commands HTML pages to use shared CSS/JS assets.

Strips inline <style> blocks and inline <script> blocks, replacing them
with <link> and <script src> references to /shared/ assets.

Usage:
  python3 scripts/convert-to-shared.py --type gallery public/galleries/*.html
  python3 scripts/convert-to-shared.py --type commands public/commands/*.html
"""

import argparse
import re
import sys
from pathlib import Path


def convert_gallery(html: str) -> str:
    """Convert a gallery HTML file to use shared assets."""
    # Remove inline <style>...</style>
    html = re.sub(r'<style>[\s\S]*?</style>\s*', '', html)

    # Replace head closing with link tags
    html = html.replace(
        '</head>',
        '<link rel="stylesheet" href="/shared/base.css">\n'
        '<link rel="stylesheet" href="/shared/gallery.css">\n'
        '</head>'
    )

    # Remove the inline <script type="module"> block (mermaid import + all gallery JS)
    # but keep the mermaid-source script tags (type="application/json")
    html = re.sub(
        r'<script type="module">\s*import mermaid[\s\S]*?</script>\s*(?=</body>)',
        '<script src="/shared/theme.js"></script>\n'
        '<script type="module" src="/shared/gallery.js"></script>\n',
        html
    )

    return html


def convert_commands(html: str) -> str:
    """Convert a commands HTML file to use shared assets."""
    # Remove inline <style>...</style>
    html = re.sub(r'<style>[\s\S]*?</style>\s*', '', html)

    # Replace head closing with link tags
    html = html.replace(
        '</head>',
        '<link rel="stylesheet" href="/shared/base.css">\n'
        '<link rel="stylesheet" href="/shared/commands.css">\n'
        '</head>'
    )

    # Remove the inline <script> block (theme + commands JS)
    # Commands pages use <script> (not type="module")
    html = re.sub(
        r'<script>\s*const THEME_KEY[\s\S]*?</script>\s*(?=</body>)',
        '<script src="/shared/theme.js"></script>\n'
        '<script src="/shared/commands.js"></script>\n',
        html
    )

    return html


def main():
    parser = argparse.ArgumentParser(description='Convert pages to shared assets')
    parser.add_argument('--type', choices=['gallery', 'commands'], required=True)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    converter = convert_gallery if args.type == 'gallery' else convert_commands
    converted = 0
    skipped = 0

    for filepath in args.files:
        if not filepath.exists():
            print(f'SKIP {filepath} (not found)')
            skipped += 1
            continue

        original = filepath.read_text(encoding='utf-8')

        # Skip already-converted files
        if '/shared/base.css' in original:
            print(f'SKIP {filepath.name} (already converted)')
            skipped += 1
            continue

        result = converter(original)

        if args.dry_run:
            orig_lines = len(original.splitlines())
            new_lines = len(result.splitlines())
            print(f'DRY  {filepath.name}: {orig_lines} -> {new_lines} lines')
        else:
            filepath.write_text(result, encoding='utf-8')
            orig_lines = len(original.splitlines())
            new_lines = len(result.splitlines())
            print(f'OK   {filepath.name}: {orig_lines} -> {new_lines} lines')
            converted += 1

    print(f'\nDone: {converted} converted, {skipped} skipped')
    return 0


if __name__ == '__main__':
    sys.exit(main())
