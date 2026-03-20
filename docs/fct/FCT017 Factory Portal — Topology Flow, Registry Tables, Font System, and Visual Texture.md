# FCT017 Factory Portal — Topology Flow, Registry Tables, Font System, and Visual Texture

**Date:** 2026-03-20
**Status:** Complete
**Related:** FCT011, FCT014, FCT015, FCT016

---

## 1. Summary

Single-session sprint covering four areas of the Factory Portal: topology page layout overhaul with flow diagrams and inline-editable registry tables, a font trial and selection system, a CSS-only background texture layer, and footer/card typography fixes. All 25 tests passing across 13 test files. Deployed to Blackbox at `:41910` via `make sync`.

---

## 2. Topology Page — Flow Diagrams and Registry Tables

### 2.1 Escalation Chain Flow Layout

The Escalation Chain section was converted from a flat CSS grid to a horizontal flow layout with directional arrow connectors. Each escalation stage is rendered as a card with a color-coded left border indicating risk level:

| Border Color | Risk Level | Stages |
|--------------|------------|--------|
| Green | Low | Initial stages |
| Amber | Medium | Intermediate escalation |
| Red | High | Final escalation / human intervention |

Arrow connectors between cards are implemented as `::after` pseudo-elements on each flow item, providing a visual left-to-right progression through the escalation chain.

The System Infrastructure section was kept as a flat grid layout but given indigo accent borders (`--accent-border`) for visual consistency with the portal's design language.

### 2.2 Job Registry Tables

A new "Job Registry" SurfaceCard was added at the bottom of the Topology page, containing two side-by-side dense tables:

- **Domain Registry** (left) — 5 domains (00-system, 10-boot, 20-ig88, 30-kelk, plus any future additions)
- **Class Registry** (right) — 8 job classes

Both tables support inline editing: clicking any label, description, or color cell opens an editable field. Saves are dispatched via PUT to `jobs.json` using the existing `updateDocument` optimistic mutation pattern already established in the portal's data layer.

### 2.3 Backend Changes

`build-jobs-json.py` was updated to include a `registry` key in the `jobs.json` output, containing both domain and class maps sourced from `jobs/registry.yaml`. The `TasksDocument` TypeScript type was extended with an optional `registry` field and a new `RegistryEntry` interface to support the inline-editable tables.

---

## 3. Font System Overhaul

### 3.1 Font Trial System

A font trial bar was built directly on the Topology page with two rows of selectors:

- **Display fonts** — 6 options for headers and hero text
- **Body fonts** — 4 options for body copy and monospace contexts

The trial system uses `data-font-trial` and `data-body-trial` attributes on the `<html>` element, which override CSS custom properties globally. This allows instant previewing of any font combination across the entire portal without page reload.

### 3.2 Font Files Added

12 font files were copied from `~/dev/shared-fonts/` to `portal/public/fonts/`:

| Font | File | Weight | Role |
|------|------|--------|------|
| Departure Mono | DepartureMono-Regular.woff2 | 400 | Display trial |
| Geist | Geist-SemiBold.woff2 | 600 | Display trial |
| Geist Pixel Line | GeistPixel-Line.woff2 | 400 | Display trial |
| Geist Pixel Circle | GeistPixel-Circle.woff2 | 400 | Display trial |
| Geist Pixel Grid | GeistPixel-Grid.woff2 | 400 | Display default |
| Basement Grotesque | BasementGrotesque-Black.woff2 | 800 | Display trial |
| Clash Grotesk | ClashGrotesk-Semibold.woff2 | 600 | Display trial |
| Input Mono Thin | InputMono-Thin.ttf | 100 | Body trial |
| Geist Mono UltraLight | GeistMono-UltraLight.woff2 | 200 | Body default |
| Geist Mono Thin | GeistMono-Thin.woff2 | 100 | Body trial |
| Monaspace Neon | MonaspaceNeon-Variable.ttf | 100-800 | Body trial |

### 3.3 Final Selection

| Context | Font | Weight |
|---------|------|--------|
| Display / Headers | Geist Pixel Grid | 400 |
| Body / Monospace | Geist Mono UltraLight | 200 |

Previous fonts (Input Sans, Inter, Input Mono) remain available as trial options. The font trial bar is kept visible for continued experimentation.

### 3.4 Branding Changes

- Hero header renamed from "factory" to "dreamfactory"
- "Factory Portal" eyebrow text removed from all pages
- Nav button font size reduced from 12px to 11px
- Base body font size set to 14px with font-weight 200

---

## 4. Background Texture

A CSS-only dual-layer dot grid texture was added on `body::before` as a fixed, non-interactive overlay (`pointer-events: none`):

| Layer | Grid Spacing | Dot Size | Opacity | Tint |
|-------|-------------|----------|---------|------|
| Primary | 40px | 0.8px | 22% | Neutral |
| Secondary | 29px | 0.6px | 12% | Indigo |

The secondary grid uses a prime-number spacing (29px) to avoid visual alignment with the primary grid (40px), creating a more organic pattern. A slow 90-second drift animation provides subtle motion. Light mode uses reduced opacity values. All page content sits above the texture via z-index layering.

---

## 5. Footer and Card Fixes

- Footer given the same translucent treatment as the header: `surface-strong` background with `backdrop-filter: blur()`
- Dependency, budget, and approval cards given explicit 11px font-size to match job description text density
- Consistent typography across all dense information surfaces

---

## 6. Files Modified

| File | Changes |
|------|---------|
| `portal/src/pages/TopologyPage.tsx` | Flow layouts, registry tables with inline editing, font trial switcher |
| `portal/src/styles/app.css` | Flow connectors, registry table styles, 10 font declarations, font trial attribute overrides, dot grid texture, footer translucence, card font fixes |
| `portal/src/lib/types.ts` | `RegistryEntry` interface, `registry` field on `TasksDocument` |
| `portal/src/components/AppShell.tsx` | "dreamfactory" hero, eyebrow removal |
| `scripts/build-jobs-json.py` | Registry key inclusion in output |
| `jobs.json` | Rebuilt with registry data (5 domains, 8 classes) |
| `portal/public/fonts/` | 12 new font files |

---

## 7. Verification

| Check | Result |
|-------|--------|
| Tests | 25/25 passing across 13 test files |
| Build | Clean (`pnpm build`) |
| Deployment | Blackbox `:41910` via `make sync` |
| Registry data | `jobs.json` includes `registry` key with 5 domains and 8 classes |

---

## 8. Next Steps

- Evaluate Geist Pixel Grid / Geist Mono UltraLight pairing over a few sessions before locking in and removing the trial bar
- Consider persisting font trial selection to localStorage so it survives page reload
- Registry table edits currently require the GSD sidecar to be running for PUT — add error handling for offline state
