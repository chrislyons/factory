# IG88040: Documentation Pattern Analysis — What We're Doing Right & Wrong

**Date:** 2026-04-12  
**Author:** IG-88  
**Purpose:** Meta-analysis of our own documentation practices across 41 IG88### documents

---

## Executive Summary

After reviewing the full IG88### documentation corpus (41 docs, ~8,500 lines), I identified clear patterns in what makes our docs effective and where we're accumulating technical debt. The strongest documents (IG88020, IG88034, IG88038) share common structure. The weakest have structural issues that propagate forward.

---

## What We're Doing Right

### 1. Statistical Rigor Format (IG88038, IG88020)

The best documents follow this pattern:
- **Executive Summary** with the headline finding
- **Hypothesis** stated upfront (falsifiable)
- **Methodology** with test universe clearly defined
- **Results** in clean tables (pairs as rows, metrics as columns)
- **Statistical Significance** section with p-values, CIs, bootstrap iterations
- **Walk-Forward Stability** showing the edge doesn't decay
- **Implementation** section translating findings to code
- **Next Steps** with concrete actions

**Example of excellence (IG88038):**
```
T1 wins in ALL 6 pairs (100%).
Mean T1-T0 difference: +0.676 PF
95% CI: [+0.560, +0.795]
P(T1 <= T0): 0.0000
Result: HIGHLY SIGNIFICANT
```

This format is immediately actionable. We should standardize on it.

### 2. "What Was Eliminated" Sections (IG88020)

IG88020 includes a table of failed strategies:
```
| Eliminated | Reason |
| H2 | PF < 1.0 with fees included |
| Price-SMA regime proxy | Circular dependency |
| Donchian/BB breakout | Overfit to bull run |
```

**This is critical institutional memory.** Without it, we'd re-test the same failing ideas. Every major research doc should include this.

### 3. Assumptions & Risks Sections (IG88024)

IG88024 explicitly lists what the research does NOT prove:
```
- H3 works on other timeframes (not yet tested)
- H3 works on other assets (NEAR, INJ showed promise but n<5)
- The edge is permanent (statistical significance ≠ future persistence)
```

This prevents overclaiming and sets clear boundaries for deployment.

### 4. Friction Always Included

Every backtest result includes friction:
- Jupiter perps: 0.25% round-trip
- Kraken spot: 0.42% round-trip
- Results that become unprofitable with friction are flagged

This discipline prevents the "paper profits" trap.

### 5. Clear Separation of IS vs OOS

Recent docs consistently separate:
- In-sample (training) period
- Out-of-sample (test) period
- Rolling window stability across periods

The walk-forward approach in IG88020 (8/8 windows profitable) is gold standard.

---

## What We're Doing Wrong

### 1. Naming Convention Violations

**Issue:** `IG88014_Indicator_Expansion_Squeeze_MeanRev_Chandelier.md`

This doc uses underscores instead of spaces, breaking the `{IG88###} {Title}.md` convention.

**Fix:** Rename to `IG88014b Indicator Expansion Squeeze MeanRev Chandelier.md` (already done in INDEX but file not renamed).

### 2. Duplicate Prefix Numbers

**Issue:** Two IG88001 documents exist:
- `IG88001 FCT060 Validation Response.md`
- `IG88001 Multi-Venue Trading Action Plan.md`

**Impact:** Confusing for lookups. One should be renumbered or merged.

### 3. Inconsistent Executive Summary Coverage

**Stats:**
- 15 docs have "Executive Summary" section
- 26 docs do NOT have one

The most readable docs (IG88034, IG88038, IG88020) all have executive summaries. The docs without them are harder to scan and extract action items from.

**Recommendation:** Make executive summary mandatory. Even a 2-sentence summary is better than none.

### 4. Research Dump vs Decision Format

Some documents (IG88003, 749 lines) are comprehensive but overwhelming. They mix:
- Research findings
- Implementation plans
- Status updates
- Historical context

**Better pattern (IG88034):**
- State the finding
- Show the evidence
- Declare the decision
- List next steps

**The 75/25 rule:** 75% of the value is in the first 25% of the document. Structure accordingly.

### 5. Small Sample Sizes Claimed as "Validated"

**Example from IG88024:**
```
Combined OOS PF: 7.281
Trade Count (n): 22
Result: "VALIDATED"
```

PF 7.281 is impressive, but n=22 is statistically fragile. A single bad trade drops PF significantly. The permutation test (Z=7.73) helps, but we should be more careful with the word "validated."

**Recommendation:** Use tiered language:
- n < 20: "Preliminary signal"  
- n 20-50: "Promising, needs more data"
- n 50-100: "Validated with caveats"
- n > 100: "Validated"

### 6. Overlap Between Documents

Multiple docs cover similar ground:
- IG88024, IG88029, IG88030 all discuss H3-A/B optimization
- IG88034, IG88035, IG88037 all discuss Mean Reversion
- IG88038, IG88039 discuss timing and recursive optimization

**Root cause:** No clear doc type taxonomy. We have:
- Research docs (findings)
- Status docs (progress)
- Reference docs (how-to)

These should be clearly labeled or separated.

### 7. Missing "Lessons Learned" in Most Docs

Only 3 of 41 docs include explicit lessons learned. The rest focus on "what we found" without "what we learned from the process."

**Example of good lesson (IG88034):**
```
Key Finding: Mean Reversion is the only strategy profitable 
in the current regime because agent competition eats 
directional edges.
```

This is valuable meta-knowledge that should be extracted and preserved.

---

## Recommended Standards

### Document Template

```
# IG88XXX: {Clear Title}

**Date:** YYYY-MM-DD  
**Author:** IG-88  
**Status:** {Draft|Active|Finalized|Archived}

---

## Executive Summary
{2-3 sentences: What did we find? What does it mean?}

## Hypothesis
{What were we testing?}

## Methodology
{Test universe, parameters, data sources}

## Results
{Clean tables, key metrics}

## Statistical Rigor
{Sample size, CIs, p-values, walk-forward}

## What Was Eliminated
{What failed and why}

## Implementation
{How to use this finding}

## Assumptions & Risks
{What could make this wrong}

## Next Steps
{Concrete actions with owners}

---

*Generated: YYYY-MM-DD | Author: IG-88*
```

### Document Types

| Type | Purpose | Required Sections |
|------|---------|-------------------|
| Research | Test a hypothesis | Hypothesis, Methodology, Results, Stats |
| Status | Report progress | Summary, Completed, Blocked, Next |
| Reference | How-to guide | Overview, Steps, Examples, Troubleshooting |
| Decision | Lock in a choice | Context, Options, Choice, Rationale, Review Date |

### Naming Hygiene

1. Always verify prefix with lookup before writing
2. Never use underscores in titles
3. Include descriptive title (not just topic keywords)
4. Update INDEX.md when adding new docs

---

## Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Docs with Executive Summary | 37% (15/41) | 100% |
| Naming violations | 2 | 0 |
| Duplicate numbers | 1 pair | 0 |
| Docs with "What Was Eliminated" | 7% (3/41) | 50%+ |
| Docs with "Assumptions & Risks" | 15% (6/41) | 100% |
| Avg doc length | 207 lines | 150-200 |
| Sample size validation notes | Rare | Always |

---

## Action Items

1. **Rename IG88014_Indicator_Expansion...** to proper format (minor)
2. **Consolidate or renumber duplicate IG88001** (minor)
3. **Apply executive summary template to future docs** (standard)
4. **Add "Lessons Learned" section to active research** (process improvement)

---

## What We're Getting Right (Meta)

Looking at the evolution from early docs (IG88001-010) to recent (IG88034-039):

**Clear improvement in:**
- Statistical rigor (early: "looks good", recent: p-values, CIs)
- Honest validation (early: "validated!", recent: "promising but n<50")
- Friction awareness (early: ignored, recent: always included)
- Structure (early: freeform, recent: template emerging)

**The trajectory is positive.** The issues above are refinements, not fundamental problems. We're learning to document like quant researchers, not developers.

---

*IG-88 Documentation Analysis | 41 documents reviewed | 2026-04-12*
