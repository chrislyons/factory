# FCT011 Factory Portal v8 — Design Overhaul and Deployment

**Date:** 2026-03-20
**Status:** Complete
**Scope:** Portal UI — typography, colour system, dark/light mode, hotkey navigation, TopologyPage enrichment
**Deployment:** `http://100.87.53.109:41910/` (Caddy + systemd, basic auth)

---

## Overview

Portal v8 is a consolidation pass that merges the aesthetic foundation of v6 with the architectural improvements from v7, then adds substantial new functionality: a complete colour system overhaul, true dark/light mode support, keyboard-driven navigation, and a significantly enriched TopologyPage. The result is a cohesive design system built on custom properties and a curated three-font stack.

## Typography

v8 originally shipped with Input Sans / Inter / Input Mono. As of FCT017, the font system has been overhauled:

| Role | Font | Source | Weight |
|------|------|--------|--------|
| Display / Headers | Geist Pixel Grid | Local woff2 | 400 |
| Body / Dense Text | Geist Mono UltraLight | Local woff2 | 200 |
| Code / Metrics | Geist Mono UltraLight | Local woff2 | 200 |

A font trial system on the Topology page allows live switching between 6 display and 4 body options. See FCT017 for full font inventory.

JetBrains Mono has been fully removed — all `.woff2` files deleted from `portal/public/fonts/` and all CSS references stripped.

## Colour Palette

The teal/neon palette from v6-v7 has been replaced with an indigo-based system implemented as CSS custom properties.

**Primary accent colours:**
- Dark mode: `#6366f1`
- Light mode: `#4f46e5`

**Agent entity colours** (constant across both modes):

| Agent | Colour | Hex |
|-------|--------|-----|
| Boot | Sky blue | `#38bdf8` |
| IG-88 | Orange | `#f97316` |
| Kelk | Purple | `#a78bfa` |
| Nan | Rose | `#fb7185` |

**Chart colours** (AnalyticsPage):
- Green: `#34d399`, Red: `#f87171`, Yellow: `#fbbf24`, Blue: `#60a5fa`, Indigo: `#6366f1`, Purple: `#a78bfa`

All tokens are defined on `:root` (dark default) with `[data-theme="light"]` overrides.

## Dark + Light Mode

Dark mode remains the primary experience. Light mode is now a first-class citizen rather than an afterthought.

**Implementation:**
- `useTheme` hook (`portal/src/hooks/useTheme.ts` — new file)
- Persists preference to `localStorage`
- Respects `prefers-color-scheme` media query on first visit
- Theme toggle button (sun/moon icon) added to AppShell header
- All component colours reference CSS custom properties, so mode switching is instant with zero re-renders of component trees

## Hotkey Navigation

Number keys provide direct page access without reaching for the mouse:

| Key | Destination |
|-----|-------------|
| `1` | Portal (landing) |
| `2` | Mission Control |
| `3` | Loops |
| `4` | Approvals |
| `5` | Budget |
| `6` | Analytics |
| `7` | Topology |
| `\` | Cycle dark/light theme |
| `Cmd+K` | Command palette (retained from v7) |

Hotkeys are registered in `AppShell.tsx` and are suppressed when focus is inside an input or textarea.

## TopologyPage Enrichment

The TopologyPage expanded from a simple 2x2 agent grid into five distinct information sections:

1. **Summary stats row** — Total agents, active count, loop count, total runs
2. **Agent network** — Per-agent cards using CSS-variable entity colours, showing individual stats (loops, runs, status)
3. **System infrastructure** — Coordinator, Memory (Graphiti/Qdrant), LLM providers, Hardware (Cloudkicker/Blackbox)
4. **Escalation chain** — Visual pipeline: auto-approve, propose-then-execute, human approval tiers
5. **Autonomous loops** — Per-agent loop capacity and current utilisation

## Landing Page Fix

The v7 badge/eyebrow text collision has been resolved. v6 layout proportions and card styles are retained, giving the landing page a clean visual hierarchy without overlapping elements.

## Files Modified

| File | Change |
|------|--------|
| `portal/src/styles/app.css` | Complete rewrite — palette tokens, font-face declarations, light mode overrides |
| `portal/src/hooks/useTheme.ts` | New file — theme hook with localStorage + prefers-color-scheme |
| `portal/src/components/AppShell.tsx` | Theme toggle button, number-key hotkey navigation |
| `portal/src/pages/TopologyPage.tsx` | Major enrichment — 5-section layout |
| `portal/src/pages/PortalPage.tsx` | Badge/eyebrow collision fix |
| `portal/src/pages/AnalyticsPage.tsx` | Chart colour palette update |
| `portal/src/pages/TopologyPage.test.tsx` | Updated assertions for new topology sections |
| `portal/public/fonts/JetBrainsMono-*.woff2` | Deleted |

## Commits

| Hash | Description |
|------|-------------|
| `673ab27` | CSS design system: palette, fonts, tokens, light mode |
| `2f1e460` | Remove JetBrains Mono fonts |
| `494548d` | Enriched TopologyPage |
| `40cca6d` | AppShell theme toggle, hotkey nav, chart palette |
| `fbb4e58` | Test fixes (matchMedia guard, topology test) |

## Verification

| Metric | Result |
|--------|--------|
| Build | Clean (`pnpm build`, 742ms) |
| Tests | 25/25 passing across 13 test files |
| TypeScript | Zero type errors |
| Deployment | Serving at `http://100.87.53.109:41910/` |

## Deployment Topology

| Version | Port | Host | Status |
|---------|------|------|--------|
| v8 (current) | 41910 | Blackbox | Running |

Portal uses Caddy reverse proxy with systemd service management and basic auth. v5 retired.

## Next Steps

- Evaluate deprecation timeline for v5 on `:41933`
- Wire live data endpoints from coordinator-rs into dashboard components
- Add WebSocket streaming for real-time agent status updates
- Consider migrating auth from basic auth to token-based session management
