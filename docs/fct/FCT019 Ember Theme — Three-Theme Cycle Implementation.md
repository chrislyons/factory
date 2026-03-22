# FCT019 Ember Theme — Three-Theme Cycle Implementation

**Date:** 2026-03-21
**Status:** Complete
**Scope:** Portal theme system overhaul

---

## Summary

Added ember as the third portal theme and made it the default. The portal now cycles through three themes via the `\` hotkey: ember, dark, light. The theme toggle button displays a distinct icon for each state.

## What Was Done

### Three-Theme Cycle

The portal previously supported two themes (dark and light). This sprint introduced **ember** as a warm, amber-toned third theme and promoted it to the default on first load. The theme cycle order is:

```
ember → dark → light → ember
```

Theme toggle button icons use a record lookup for three-state display:

| Theme | Icon |
|-------|------|
| Ember | ◆    |
| Dark  | ☾    |
| Light | ☀    |

### Ember Palette

| Token        | Value     |
|--------------|-----------|
| Background   | `#352619` |
| Accent       | `#FFB800` |
| Text         | `#FFFDF9` |

### Files Changed

**`portal/src/hooks/useTheme.ts`**
- Theme type extended from `"dark" | "light"` to `"dark" | "light" | "ember"`
- Cycle logic updated for three-state rotation
- Default theme set to `"ember"`
- Removed OS `matchMedia` watcher (no longer auto-detecting system preference)

**`portal/src/styles/app.css`**
- Added `[data-theme="ember"]` block with 23 CSS custom property tokens
- Introduced `--bg-gradient-top`, `--bg-gradient-bottom`, `--bg-radial-1`, `--bg-radial-2` variables across all three theme blocks
- Body background unified to a single CSS rule using the new gradient/radial variables (eliminates per-theme body rules)

**`portal/src/components/AppShell.tsx`**
- Theme button updated to use a record lookup (`{ ember: "◆", dark: "☾", light: "☀" }`) for icon display
- Cycle function updated to handle three-state transition

## Technical Decisions

- **Ember as default:** The warm palette better suits the factory/industrial brand identity and provides stronger visual differentiation from standard dark/light modes.
- **Removed OS matchMedia watcher:** With three themes, auto-detecting system dark/light preference adds ambiguity. Users explicitly choose their theme via the toggle.
- **CSS variable unification:** Rather than maintaining separate body background rules per theme, all themes now define gradient and radial variables consumed by a single body rule. This reduces duplication and makes future theme additions simpler.

## Build Verification

- Zero TypeScript errors
- 117 Vite modules transformed
- Deployed to Blackbox `:41910` via `make sync`

## Next Steps

- Monitor user feedback on ember palette contrast ratios
- Consider persisting theme choice to localStorage (if not already)
- Potential refinement of ember accent colour for accessibility compliance
