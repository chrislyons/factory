# BTI003 Architecture Diagram Sync and Navigation

**Date:** 2026-02-01
**Status:** Complete

## Summary

Synced boot-site architecture diagram rendering with each project's source-of-truth `architecture-gallery.html`, added per-project mermaid theming, InputMono font, and Finder-style arrow key navigation.

## Changes

### Font & Theming (commit 61666e3)
- Added InputMono-Regular font (`public/fonts/input-mono/`)
- Added `MermaidConfig` interface to `src/types/architecture.ts`
- Updated `MermaidDiagram` component to accept per-project `mermaidConfig` with themeVariables, flowchart curve, sequence settings
- Added `mermaidConfig` to all 8 architecture projects with source-matched colors and curves

### Per-Project Theme Fixes
- **claudezilla**: blue `#3B82F6` → orange `#FF6B00`, v0.5.5 → v0.5.6, 27 tools, 12-tab pool, added session cleanup + slot reservation diagrams
- **2110-audio-io**: purple `#8B5CF6` → orange `#FFA500`
- **orpheus-sdk, ondina, osdevents**: `monotoneY` curve
- **claudezilla, hotbox, listmaker, 2110-audio-io, max4live-mcp**: `basis` curve

### UI Improvements
- Merged quickNav buttons into sticky header row (right-aligned, horizontal scroll on mobile)
- Removed keyboard hint badges from header
- Increased header font sizes and padding

### Finder-Style Arrow Key Navigation (commit da212cc)
- **Up/Down**: Move focus between diagram headers
- **Right**: Expand focused diagram
- **Left**: Collapse focused diagram
- **a**: Expand all, **Esc**: Collapse all + clear focus
- Focused diagram shows ring highlight, auto-scrolls into view
- Lifted expand/collapse state to parent `ArchitectureContent` component
- Added `scrollbar-hide` CSS utility

## Files Modified
- `src/types/architecture.ts` — MermaidConfig interface
- `src/components/ui/MermaidDiagram.tsx` — Controlled component with focus support
- `src/pages/ProjectArchitecture.tsx` — Keyboard navigation, lifted state
- `src/styles/fonts.css` — InputMono @font-face
- `src/index.css` — scrollbar-hide utility
- `src/lib/architectures/*.ts` — All 8 project files updated
- `public/fonts/input-mono/InputMono-Regular.ttf` — New font file

## Commits
- `61666e3` feat: sync architecture diagrams with source HTML galleries
- `14812c1` ui: increase architecture header row font size
- `38a7e41` ui: merge quickNav buttons into architecture header row
- `8510f00` ui: remove keyboard hint badges from architecture header
- `da212cc` feat: add Finder-style arrow key navigation to architecture pages
- `153dca4` ui: add version left margin and header vertical padding
- `d634594` ui: increase version label margin to ml-4
