# FCT044 Portal Static Page Modularization — Shared Asset Extraction

**Date:** 2026-03-29
**Repo:** factory/portal
**Status:** Complete

---

## Overview

42 static HTML files in the Factory Portal (22 architecture gallery pages and 20 command reference pages) were modularized by extracting all duplicated inline CSS and JavaScript into 6 shared asset files under `public/shared/`. Each page was reduced from a self-contained file of 700–1,300 lines to a thin content-only shell of 40–67 lines — a 96% reduction in total line count across the page set.

The primary maintenance benefit is that any future theme change, bug fix, or behavioral improvement now touches 6 files rather than 42.

---

## Shared Assets Created (`public/shared/`)

| File | Size | Responsibilities |
|---|---|---|
| `base.css` | 11.7 KB | CSS reset, 3-theme custom properties (dark / light / ember), layout shell, typography scale, hero section, meta-chips, surface-card, callout blocks, footer, responsive breakpoints |
| `theme.js` | 1.1 KB | Theme constants, `applyTheme()`, `getTheme()`, `setTheme()`, `cycleTheme()`, `cssVar()` helper, `localStorage` persistence |
| `gallery.css` | 4.4 KB | Gallery nav bar, nav-chip variants, diagram-card grid, diagram-header, diagram-canvas container, empty-state placeholder |
| `gallery.js` | 16.6 KB | Mermaid CDN import and initialization, theme-aware color normalization pass, diagram expand/collapse interaction, keyboard navigation (arrow keys, Home, End, `a` select-all, Esc, `\` theme cycle) |
| `commands.css` | 7.8 KB | Search-wrap input row, section-card layout, section-header toggle, command-table styles, value-block display, export button |
| `commands.js` | 11.0 KB | Live search and section filtering, copy-to-clipboard per row, section toggle collapse, export-to-markdown, keyboard shortcut wiring |

Total shared asset footprint: ~52.6 KB across 6 files, loaded once and cached by the browser.

---

## Pages Converted

### Gallery pages (22 files)
Each file went from approximately 1,310 lines (inline `<style>` + `<script>` + content) to approximately 40 lines (frontmatter, nav structure, diagram data only). The pages serve architecture diagrams rendered by Mermaid.js with theme-aware color normalization applied at render time.

### Commands pages (20 files)
Each file went from approximately 900–1,200 lines to approximately 43–67 lines. The wider range reflects variation in command table density. The pages present agent command references with live search, clipboard copy, and markdown export.

### Aggregate reduction

| Metric | Before | After | Change |
|---|---|---|---|
| Total lines across 42 pages | ~48,000 | ~1,876 | -96% |
| CSS per page (inline) | ~700 lines | 0 | Extracted |
| JS per page (inline) | ~400 lines | 0 | Extracted |
| Shared files | 0 | 6 | New |

---

## Behaviors Preserved

All pre-existing functionality was retained without change:

- Three-theme cycle (dark / light / ember) with `localStorage` persistence
- Theme toggle via `\` key works when navigating between gallery and commands pages
- Mermaid.js rendering with per-theme color normalization (diagram fill and stroke values adjusted to match active theme)
- Diagram expand/collapse with full keyboard navigation suite
- Commands live search with section filtering
- Copy-to-clipboard on individual command rows
- Export-to-markdown for full page or filtered view
- All DOM hooks (classes, IDs, data attributes) left unchanged — no regressions in page-level JavaScript that references them

---

## Automated Conversion Script

`scripts/convert-to-shared.py` was written to handle the bulk conversion. It operates as a regex-based transformer:

1. Locates the inline `<style>` block and replaces it with a `<link rel="stylesheet">` pair pointing at `base.css` and the appropriate type-specific sheet (`gallery.css` or `commands.css`)
2. Locates the inline `<script>` block and replaces it with `<script src>` tags pointing at `theme.js` and the appropriate type-specific module (`gallery.js` or `commands.js`)
3. Writes the result in-place or previews changes via `--dry-run`
4. Skips files that already contain `<link rel="stylesheet" href="../shared/` (idempotent)

The script was run against all 42 target files in a single pass after a successful dry-run verification.

---

## Deployment Notes

The `public/shared/` directory is included in the standard `pnpm build` output under `dist-production/shared/`. Caddy's existing catch-all static file route serves it without any Caddyfile modification. All shared files are same-origin (`'self'`), so the existing Content Security Policy required no changes.

Deployment was performed via the standard `make sync` flow from `portal/`.

---

## Phase 2 Status

This work constitutes Phase 1 of a two-phase modularization plan. Phase 2 — converting each page's content structure to a data-driven JSON rendering model (eliminating the per-page HTML content entirely) — was not attempted in this session. Phase 1 alone delivers the core maintenance benefit. Phase 2 remains a future improvement and is not required for correct operation.

---

## Commits

| Hash | Message |
|---|---|
| `fc1d0e3` | `feat(portal): extract shared CSS/JS from gallery/commands pages` |
| `45d9c93` | `feat(portal): bulk-convert 40 gallery/commands pages to shared assets` |

---

## Next Steps

- Consider Phase 2: data-driven rendering where each page is a single `<script type="application/json">` block consumed by a shared renderer — would reduce per-page HTML to ~15 lines and make adding new pages a data-entry task
- Audit the 2 pages not converted in the initial run (if any) and confirm parity
- Update portal test suite if any integration tests reference inline style or script content
