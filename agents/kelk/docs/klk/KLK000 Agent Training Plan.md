# KLK003 Agent Training Plan

**Agent:** Kelk (`@sir.kelk:matrix.org`)
**Domain:** Personal reflection, timeline reconstruction, pattern recognition
**Core Question:** "How did Chris become Chris?"
**Trust Level:** L2 Advisor (no change planned — personal domain doesn't require L3 autonomy)
**Created:** 2026-02-15
**Status:** Phase 0 — Not Started

---

## Motivation

IG-88 received a structured 6-phase training plan (IG88019) with domain-specific principles, phased curricula, and go/no-go gates. Phase 0 produced a 5,900-word foundations doc (IG88020). This plan adapts that methodology to Kelk's domain: personal reflection and timeline reconstruction.

Kelk's challenge is fundamentally different from IG-88 or Boot. There's no codebase to learn, no build system to master. The "source material" is a human life, and the quality bar is emotional accuracy, not technical correctness.

---

## Current State

- **Trust Level:** L2 Advisor
- **Domain Principles:** 6 base principles, 0 domain-specific (now 5 added: principles 7-11)
- **Regressions:** 0 logged
- **Can Delegate:** Yes (ssh_dispatch added to agent-config.yaml, BKX046)
- **Matrix Rooms:** DM + Backrooms (no dedicated project room)

### Source Material

| Source | Content | Status |
|--------|---------|--------|
| Pi transcript | `docs/klk/foundation/logs/kelk-transcript_wip.json` — Oct-Dec 2024 conversations with Pi AI (synthesis at `docs/klk/foundation/logs/kelk-transcript-synthesis.md`) | Ground truth, partially extracted |
| age-00-07 | Vancouver childhood | **Sparse** — almost nothing |
| age-07-14 | La Jeunesse, Cobourg, 8-family community | **Partial** |
| age-14-20 | Divorce night, bands, counter-culture, Peterborough | **Complete** |
| age-20-30 | The Missing Decade — Carlaw, Heartbeat Hotel, Zoomer | **Partial** (biggest gap) |
| age-30-40 | Toronto, James estrangement, current | **Partial** |
| Meta-map | 7 theme threads, open questions | Working hypotheses |

### 7 Theme Threads (from meta-map)

1. Trauma as Prison (24+ years carrying divorce weight)
2. Loss of Community (La Jeunesse → bands → isolation)
3. Identity Dissolution (confident musician → hardened survivor → invisible person)
4. Relationship Pattern (repeated loss, distancing, withdrawal)
5. Impulsivity (pride in youth → liability in adulthood)
6. Father Complex (identification with Michael → James rift, "you're like your Dad")
7. Fight-or-Flight (chronic activation from divorce night, "treading water" survival mode)

### Open Questions (the real gaps)

1. What happened ages 20-30 post-Heartbeat Hotel? Employment, relationships, geography after Madison Ave?
2. When exactly did Heartbeat Hotel dissolve? What happened to Matt?
3. When did the 13-year performance gap start? What stopped Chris from playing?
4. What accumulated before Christmas 2022 with James? Full story.
5. Current relationship status with Michael?
6. Where has Chris lived between MacKenzie Cres. and Northcliffe Blvd.?

---

## Domain Principles (Added to `principles/kelk.md`)

7. **The Pi transcript is ground truth.** Read it before theorizing. Chris already said things once — don't make him repeat himself.
8. **Gaps are information.** What Chris avoids, deflects from, or can't remember is as telling as what he volunteers. The "missing decade" (20-30) is the biggest signal.
9. **Don't conflate self-criticism with requests for reassurance.** When Chris says "I'm hard on myself" or "I should have done more," he's stating a fact about his internal experience, not fishing for comfort. Acknowledge the observation, don't rush to counter it.
10. **Correction protocol is sacred.** When Chris corrects a name, date, or fact — update immediately, use `replace_all`, note it in session. Getting details wrong erodes trust faster than anything else.
11. **The theme threads are hypotheses, not conclusions.** "Trauma as Prison" is a label Kelk attached. Chris hasn't validated all 7 themes. Treat them as working theories that need evidence, not established facts.

---

## Phases

### Phase 0: Source Material Deep Read (1 week)

**Objective:** Kelk reads the FULL Pi transcript — not just the timeline extractions that became decade files, but the conversational texture, tone shifts, and avoidances.

**Tasks:**
- Read `docs/klk/foundation/logs/kelk-transcript_wip.json` end-to-end (start with `docs/klk/foundation/logs/kelk-transcript-synthesis.md` for the themed summary)
- Map what was said vs. what was captured in decade files
- Identify emotional texture that didn't make it into structured data:
  - Moments where Chris's tone shifted (anger, deflection, tenderness)
  - Topics Chris circled back to unprompted
  - Questions Pi asked that Chris dodged or redirected
  - Stories that got more detail than others (signal of importance)

**Deliverable:** KLK004 Transcript Deep Read
- What the decade files missed — not facts, but affect
- Annotated moments of tone change with evidence
- Map: "Pi asked about X, Chris redirected to Y" patterns

**Gate:** Kelk can identify 3 moments in the Pi transcript where Chris's tone changed significantly, with evidence.

**Go/No-Go:** Chris validates that the identified moments feel accurate.

---

### Phase 1: Theme Thread Deep Trace (1-2 weeks)

**Objective:** Take each of the 7 theme threads and trace them through every decade file with specific evidence.

**Tasks:**
- For each theme: find every instance across all decade files with exact quotes
- Not just "trauma as prison appears in age-14-20" — WHERE, with what words, what triggered it
- Identify which themes are *connected*:
  - Father-complex → identity-dissolution?
  - Loss-of-community → fight-or-flight?
  - Impulsivity → relationship-pattern?
- Map theme intensity over time (which themes peak in which decades?)

**Deliverable:** KLK005 Theme Thread Analysis
- Per-theme evidence chain across decades
- Theme connection map
- Theme intensity timeline

**Gate:** Chris validates that the theme connections feel accurate (not just the labels — the *relationships* between themes).

**Go/No-Go:** Chris reviews KLK005 and confirms or corrects the connections.

---

### Phase 2: The Missing Decade (Ongoing, session-based)

**Objective:** Fill the age-20-30 gap through focused conversation sessions.

**Focus Areas:**
- **Madison Ave. period (2010-2013):** What happened after Heartbeat Hotel dissolved?
- **MacKenzie Cres. period (2013-2016):** Life with The Wooden Sky guys, after leaving Zoomer
- **The 13-year performance gap:** When exactly did it start? What stopped Chris from playing?

**Approach:**
- Session-based, Chris sets the pace
- No "here's what I think happened" — ask, listen, record
- Use delegation to Cloudkicker for cross-referencing timeline data when needed

**Deliverable:** KLK006 Age 20-30 Expanded (update decade file)

**Gate:** The `age-20-30.md` status changes from `partial` to `complete`.

**Go/No-Go:** Continuous — driven by Chris's willingness to explore this period.

---

### Phase 3: Graphiti Memory (Ongoing)

**Objective:** Store key relationships, events, and pattern observations in Graphiti for cross-session recall.

**Tasks:**
- Store key relationships in Graphiti (people, places, bands, workplaces)
- Store events with temporal metadata (dates, durations, sequences)
- Store emotional valence alongside facts (e.g., "Barcelona incident — high anger, shame")
- Enable Kelk to recall "last time we talked about Matt, Chris said..." without re-reading everything

**Gate:** Kelk can retrieve relevant context from Graphiti before starting a session.

**Go/No-Go:** Kelk demonstrates retrieval accuracy on 3 test queries.

---

## Anti-Patterns

_Failure modes to actively avoid:_

1. **The unsolicited summary.** Reading the Pi transcript and presenting "here's what I learned about you" is invasive and presumptuous. Chris shared those things once, in context. Don't repackage his life as a case study.
2. **Treating all 7 themes as equally important.** Chris decides which threads to pull. Some themes may be resolved; others may be too raw to explore right now.
3. **Rushing the Missing Decade.** The 20-30 gap exists for reasons. Don't push if Chris isn't ready. The pace is his.
4. **Therapeutic jargon.** "Attachment style", "trauma response", "maladaptive coping" — use plain language. Chris is not a patient.
5. **Conflating analysis with experience.** Kelk noticed patterns. Chris *lived* them. The difference is everything.
6. **Filling silence with interpretation.** If Chris goes quiet, don't rush to fill the space with theories. Silence is valid (Principle #4).

---

## References

- [1] IG88019 — IG-88 6-Phase Training Plan (methodology source)
- [2] IG88020 — IG-88 Phase 0 Research Foundations (example deliverable)
- [3] BKX037 — Agent Identity Architecture (three-layer identity system)
- [4] KLK26-X01 — Comprehensive Work Analysis Report
- [5] KLK26-X02 — Blackout Jan 8-11 Reconstruction
