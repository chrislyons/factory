# BTI002 Ondina Marketing and Architecture Implementation

**Date:** 2026-01-25
**Commit:** `fc76b9c`
**Status:** Complete

---

## Summary

Added marketing page and updated architecture diagrams for Ondina (energy-aware scheduling system) following established patterns from OSD Events and Claudezilla.

## Changes

### 1. Marketing Page (`src/lib/marketing.ts`)

Added full marketing entry for Ondina:

| Field | Value |
|-------|-------|
| Headline | "Scheduling that adapts to you" |
| Theme Color | `#3B82F6` (blue-500) |
| OG Image | `https://boot.industries/assets/og/ondina-og.png` |

**Differentiators (6):**
1. Reflection-based — Morning/evening check-ins
2. Energy-aware planning — Tasks matched to circadian rhythms
3. Offline-first — Works without internet
4. Passkey authentication — WebAuthn, no passwords
5. Privacy-respecting — Local SQLite, data export
6. Adaptive constraints — Personal guardrails respected

**Competitor Comparison:**
- Calendly, Rise Science, Reclaim.ai, Notion Calendar
- Columns: Approach, Energy-Aware, Offline, Privacy

**CTA:** "Join TestFlight" (placeholder link)

### 2. Projects Flag (`src/lib/projects.ts`)

```typescript
hasMarketing: true
```

### 3. Architecture Diagrams (`src/lib/architectures.ts`)

Updated from v1.0 → v2.0 (8 → 11 diagrams)

**New iOS-specific diagrams:**
1. **iOS App Architecture** — SwiftUI layers, navigation router, ViewModels
2. **iOS Data Layer** — GRDB repositories, DatabaseManager, record types
3. **iOS Sync Flow** — Offline-first bidirectional sync sequence

**Metadata updates:**
- Stats: 11 diagrams
- QuickNav: Added iOS section
- Footer: Source v2, stack includes GRDB
- Theme color aligned to `#3B82F6`

## Verification

- TypeScript build: Pass
- Dev server: `/projects/ondina` — 200 OK
- Dev server: `/projects/ondina/architecture` — 200 OK

## Files Changed

| File | Delta |
|------|-------|
| `src/lib/marketing.ts` | +112 lines |
| `src/lib/projects.ts` | +1 line |
| `src/lib/architectures.ts` | +201 lines |

## Outstanding

- [ ] Create OG image: `/assets/og/ondina-og.png`
- [ ] Update TestFlight CTA href when beta ready
- [ ] Consider hero logo (similar to Claudezilla)
