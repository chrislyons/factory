# FCT018 Factory Portal — Mobile Optimization and UX Polish Sprint

*Boot Industries — 2026-03-21 — Sprint Report*

---

## Overview

Focused pass on portal mobile usability and cross-page UX consistency. The primary goals were eliminating horizontal overflow on small screens, consolidating shell width logic, and tightening the visual density of interactive controls across Jobs, Loops, Objects, System, and agent detail pages.

---

## Shell Width

Removed the separate mobile override in favor of a single unified formula: `min(1410px, 92vw)`. Previously the desktop and mobile breakpoints used different vw ratios, creating inconsistency. Now the same ratio applies everywhere — the shell simply scales down on narrow viewports without any conditional logic.

---

## Job Cards

Three targeted fixes for the Jobs Tracker card layout on mobile:

- **Checkbox border** increased to `1.5px border-strong` to ensure it remains visible against the card background in both light and dark mode
- **Description and meta rows** use a negative margin technique to break out of the card's internal padding, allowing them to span the full card width on narrow viewports
- **Action buttons** rendered side-by-side in a 34px-height row instead of stacking vertically, saving significant vertical space per card

---

## Loop Controls Redesign

The Loop Controls panel was rebuilt as a composite row rather than separate elements:

- Search input and trigger button are fused into a single contiguous control
- Filter chips rendered as a tight inline strip (no excessive gap)
- On mobile, the 2x2 grid layout replaces the single-column stack, fitting more controls in the visible area without scrolling

---

## System Topology Page

- Renamed from "System" to "System Topology" in the page `<h1>` (nav button label unchanged to preserve keyboard shortcut muscle memory)
- On mobile, the topology flow now stacks vertically; tier rows wrap rather than overflow horizontally
- Font trial panel, mini-grid, and registry tables all scale down with reduced padding and font size at the mobile breakpoint — they are reference tools, not primary content

---

## Agent Detail Pages

Compact pass across all agent cards:

- All cards use reduced padding and tighter line-height
- `dashboard-grid` gap regularized across agents
- Mobile run history table collapses to a single-column layout (timestamp + status stacked, no horizontal scroll required)
- Tab row (`Overview`, `Runs`, `Config`, etc.) uses `overflow-x: auto` horizontal scroll rather than wrapping or truncating

---

## Page Title Renames

Three page `<h1>` titles updated to be more descriptive without changing nav button text:

| Page | Old Title | New Title |
|------|-----------|-----------|
| Jobs | Jobs | Jobs Tracker |
| Objects | Objects | Object Index |
| System | System | System Topology |

Nav buttons (hotkeys 1–5) unchanged.

---

## iOS Zoom Prevention

Added `maximum-scale=1.0` to all viewport meta tags. Without this, iOS Safari zoom-on-focus behavior causes layout shift when tapping inputs, which is disorienting on the Loop Controls panel and job search field.

---

## Horizontal Overflow Fixes

Two systemic causes of horizontal overflow addressed:

1. **Page content children:** `min-width: 0` + `max-width: 100%` applied to flex/grid children that were escaping their containers at narrow widths (notably the Topology tier rows and agent card grids)
2. **Font trial bar:** `overflow: hidden` added to prevent the trial strip from pushing the page width past the shell boundary

---

## Objects Page

Hotkey hints (e.g., `⌘K`, `C`) hidden via `display: none` at the mobile breakpoint. They are keyboard-only affordances with no touch equivalent and were consuming visual space without utility.

---

## Status

- Tests: 17/17 passing (no regressions)
- Build: clean (`pnpm build`)
- Deployed: `make sync` to Blackbox :41910

## Next Steps

- Audit Loops page run-list cards for the same single-column mobile treatment
- Consider sticky header on mobile (currently scrolls away)
- Analytics page charts: verify responsiveness on 375px viewport
