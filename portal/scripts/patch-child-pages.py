#!/usr/bin/env python3
"""Patch commands/ and galleries/ child pages for mobile layout fixes.

Idempotent — safe to run multiple times.

Fixes applied:
  1. Font paths: ../../shared-fonts/... -> /fonts/...
  2. Mobile shell width: 96vw override in 900px media query
  3. Command code block overflow (commands only, 900px query)
  4. Gallery diagram overflow + nav chip wrap (galleries only, 640px query)
  5. Hero meta stacking (both, 900px query)
  6. Brand header: link to /pages/docs.html, rename to dreamfactory
"""

import glob
import os
import re

PORTAL_PUBLIC = os.path.join(os.path.dirname(__file__), "..", "public")

# --- Fix 1: Font paths ---
FONT_REPLACEMENTS = [
    (
        '../../shared-fonts/geist/geist-pixel/GeistPixel-Square.woff2',
        '/fonts/GeistPixel-Square.woff2',
    ),
    (
        '../../shared-fonts/geist/geist-mono/GeistMono-UltraLight.woff2',
        '/fonts/GeistMono-UltraLight.woff2',
    ),
]

# --- Fix 2: Mobile shell width (injected into 900px media query) ---
SHELL_WIDTH_CSS = """\

  main,
  .site-header__inner,
  .footer-notes,
  footer .inner {
    width: 96vw;
  }"""

# --- Fix 3: Command code block overflow (commands only, 900px query) ---
COMMAND_OVERFLOW_CSS = """\

  .value-block {
    max-width: 100%;
    overflow-x: auto;
  }

  .value-text {
    word-break: break-all;
  }

  .desc-text {
    display: block;
    padding: 4px 12px 8px;
  }"""

# --- Fix 5: Hero meta stacking (both, 900px query) ---
HERO_META_CSS = """\

  .hero-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .meta-chip {
    font-size: 10px;
  }"""

# --- Fix 4a: Replace existing diagram-canvas in 640px query with enhanced version ---
DIAGRAM_CANVAS_OLD = """  .diagram-canvas {
    margin: 12px 12px 12px;
    padding: 14px;
  }"""

DIAGRAM_CANVAS_NEW = """  .diagram-canvas {
    margin: 8px;
    padding: 10px;
    overflow-x: auto;
  }

  .diagram-canvas svg {
    max-width: 100%;
    height: auto;
  }"""

# --- Fix 4b: Gallery nav chip wrap (galleries only, 640px query) ---
GALLERY_NAV_CSS = """\

  .gallery-nav {
    flex-wrap: wrap;
  }

  .nav-chip {
    font-size: 10px;
    padding: 5px 8px;
  }"""

# --- Fix 6: Brand header ---
BRAND_OLD = '<span class="brand__title">codex-commandsheets</span>'
BRAND_NEW = '<a class="brand__title" href="/pages/docs.html">dreamfactory</a>'

BRAND_CSS_OLD = """.brand__title {
  font-family: var(--font-display);
  font-size: 14px;
  color: var(--text);
}"""

BRAND_CSS_NEW = """.brand__title {
  font-family: var(--font-display);
  font-size: 14px;
  color: var(--text);
  text-decoration: none;
}"""


def inject_before_closing_brace(html, media_query_marker, css_to_inject):
    """Inject CSS rules just before the closing } of a specific media query block.

    Finds the media query by marker string, then locates its closing brace
    by counting brace depth.
    """
    idx = html.find(media_query_marker)
    if idx == -1:
        return html

    # Find the opening { of the media query
    brace_start = html.find("{", idx)
    if brace_start == -1:
        return html

    # Walk forward counting braces to find the matching close
    depth = 1
    pos = brace_start + 1
    while pos < len(html) and depth > 0:
        if html[pos] == "{":
            depth += 1
        elif html[pos] == "}":
            depth -= 1
        pos += 1

    # pos is now just past the closing }
    close_pos = pos - 1  # index of the closing }

    # Check if already injected — use a unique multi-word phrase from the CSS block
    # Pick the longest rule line as sentinel (more specific than just a selector)
    sentinel_lines = [l.strip() for l in css_to_inject.strip().splitlines() if l.strip() and ":" in l]
    if sentinel_lines:
        sentinel = max(sentinel_lines, key=len)
        if sentinel in html[idx:close_pos]:
            return html

    # Inject before the closing }
    return html[:close_pos] + css_to_inject + "\n" + html[close_pos:]


def patch_file(filepath, is_commands):
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    original = html

    # Fix 1: Font paths
    for old, new in FONT_REPLACEMENTS:
        html = html.replace(old, new)

    # Fix 6: Brand CSS (add text-decoration: none)
    html = html.replace(BRAND_CSS_OLD, BRAND_CSS_NEW)

    # Fix 6: Brand HTML
    html = html.replace(BRAND_OLD, BRAND_NEW)

    # Fix 2: Shell width in 900px query
    html = inject_before_closing_brace(html, "@media (max-width: 900px)", SHELL_WIDTH_CSS)

    # Fix 5: Hero meta stacking in 900px query
    html = inject_before_closing_brace(html, "@media (max-width: 900px)", HERO_META_CSS)

    if is_commands:
        # Fix 3: Command overflow in 900px query
        html = inject_before_closing_brace(html, "@media (max-width: 900px)", COMMAND_OVERFLOW_CSS)
    else:
        # Fix 4a: Replace diagram-canvas in 640px query with enhanced version
        html = html.replace(DIAGRAM_CANVAS_OLD, DIAGRAM_CANVAS_NEW)
        # Fix 4b: Gallery nav chip wrap in 640px query
        html = inject_before_closing_brace(html, "@media (max-width: 640px)", GALLERY_NAV_CSS)

    if html != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return True
    return False


def main():
    commands_dir = os.path.join(PORTAL_PUBLIC, "commands")
    galleries_dir = os.path.join(PORTAL_PUBLIC, "galleries")

    commands_files = sorted(glob.glob(os.path.join(commands_dir, "*.html")))
    galleries_files = sorted(glob.glob(os.path.join(galleries_dir, "*.html")))

    print(f"Found {len(commands_files)} commands files, {len(galleries_files)} galleries files")

    patched = 0
    for f in commands_files:
        if patch_file(f, is_commands=True):
            patched += 1
            print(f"  patched: {os.path.basename(f)}")
        else:
            print(f"  skipped: {os.path.basename(f)} (already patched)")

    for f in galleries_files:
        if patch_file(f, is_commands=False):
            patched += 1
            print(f"  patched: {os.path.basename(f)}")
        else:
            print(f"  skipped: {os.path.basename(f)} (already patched)")

    print(f"\nDone. {patched}/{len(commands_files) + len(galleries_files)} files patched.")


if __name__ == "__main__":
    main()
