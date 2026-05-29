---
name: evidence-calibration-review
description: "Use when you want a per-claim evidence-tier audit on a text artifact before it ships — assign T1-T6 tiers to every load-bearing claim, surface calibration mismatches (high confidence on weak evidence, or honesty-theater under-claiming), and flag P11 (citation-as-decoration), P17 (pile-of-anecdotes-as-evidence), P54 (unverifiable single-source) patterns. Encodes the Evidence & Calibration deliberator role from the agent-council 5-perspective quality gate. Use standalone for fast evidence audit, or compose with the other 4 deliberator skills."
version: "0.1.1"
type: "codex"
tags: ["Quality Gate", "Evidence", "Calibration", "Council Deliberator"]
created: "2026-05-29"
valid_until: "2026-11-29"
derived_from: "prompts/evidence.md in Avyayalaya/agent-council"
tested_with: ["Claude Sonnet 4.6", "Claude Opus 4.6", "GPT-4o"]
license: "MIT"
composes_with:
  - package: "agent-council"
    skill: "skeptic-review"
    relation: "use_together"
    reason: "Skeptic surfaces unaddressed counter-positions; Evidence & Calibration tiers the claims those positions rest on. Together they catch weak-evidence claims masquerading as load-bearing."
  - package: "agent-council"
    skill: "adjudicator-synthesis"
    relation: "produces_input_for"
    reason: "Per-claim tier map + calibration issues feed directly into the Adjudicator's verdict policy."
  - package: "pm-skills"
    skill: "discovery-research"
    relation: "use_after"
    reason: "Discovery & Research produces evidence-graded findings; Evidence & Calibration audits whether downstream artifacts maintain the tiers honestly."
  - package: "pm-skills"
    skill: "competitive-market-analysis"
    relation: "use_after"
    reason: "Competitive analyses are claim-dense; Evidence & Calibration catches T5/T6 claims presented as T2 conclusions."
  - package: "pm-skills"
    skill: "metric-design-experimentation"
    relation: "use_after"
    reason: "Metric and experiment claims are particularly prone to over-claiming (sample → population). Evidence & Calibration catches these."
capability_summary: "Produces a structured Evidence & Calibration critique of a text artifact: per-claim tier assignment on the standard T1-T6 scale (with quoted claim + status + fix), calibration issues (high-confidence-on-weak-evidence and under-claimed-on-verified inversions), P11/P17/P54 pattern flags, would_block + irreducible flags. Output is fenced JSON suitable for downstream verdict aggregation."
input_schema:
  artifact: "string or path — the text artifact to audit (prose with claims clearly identifiable)"
  artifact_type: "string — optional, e.g., 'spec', 'memo', 'analysis', 'pitch'"
  domain_context: "object or path — optional, domain-specific evidence-tier rubric overrides"
  prior_round_critiques: "object — optional, all 4 R1 critiques from other deliberators when running Round 2 cross-read rebuttal"
output_schema:
  role: "Constant: evidence"
  round: "1 (independent critique) or 2 (cross-read rebuttal)"
  score: "1-5 where 1 = every load-bearing claim is unsourced or mis-tiered, 5 = every load-bearing claim is correctly tiered and well-calibrated"
  claim_tier_map: "Array of {claim, tier, status, fix} for each load-bearing claim"
  calibration_issues: "Array of strings naming over-claimed and under-claimed sentences"
  p11_p17_p54_flags: "Array of strings naming detected patterns (citation-as-decoration, pile-of-anecdotes, unverifiable single-source)"
  would_block: "Boolean — true if any load-bearing claim is T5/T6 without acknowledgment, or calibration inverted"
  irreducible: "Boolean — true only if evidence base is too thin for the claims being made; restructure required"
  notes: "≤2 sentences on overall evidence posture"
example_invocation: "examples/evidence-on-pricing-claim.md"
---

## Purpose

Run a per-claim evidence-tier audit on a text artifact before it ships. The Evidence & Calibration role reads the artifact claim by claim and asks one question per claim: **what tier of evidence supports it, and is the artifact's stated confidence consistent with that tier?**

A claim asserted with high confidence on Tier 6 (inferred) evidence is a calibration failure. A claim hedged with "perhaps" when the evidence is Tier 1 (primary source, verified) is also a calibration failure — under-claiming is its own honesty failure. The skill catches both directions.

This is the boring and the load-bearing role on the panel. "Where is the source for X?" is the question that ends careers. Evidence & Calibration surfaces every unsourced claim before it ships.

The skill encodes the Evidence & Calibration role from the `agent-council` 5-deliberator quality gate. Use standalone for fast evidence audit, or compose with the other 4 deliberator skills for fuller coverage.

## When to Use / When NOT to Use

**Use this skill when:**
- A claim-dense artifact (analysis, memo, public pitch) is about to ship and you want every load-bearing claim tiered
- You suspect over-claiming (high confidence on weak evidence) or under-claiming (hedging what is actually verified) and want both directions surfaced
- A piece relies on attributions ("X said Y" / "Microsoft did Z") and you want each verified or hedged appropriately
- You need to catch P11 (citation-as-decoration), P17 (pile-of-anecdotes-as-evidence), or P54 (unverifiable-single-source) patterns explicitly
- You are running a multi-deliberator review and need the Evidence & Calibration seat filled

**Do NOT use this skill when:**
- You need a structural critique (load-bearing claims, counter-positions) — use [skeptic-review](../skeptic-review/) instead
- You need a voice critique (banned patterns, register check, CXO test) — use [voice-identity-review](../voice-identity-review/) instead
- You need a strategic-fit check (goal alignment, opportunity cost) — use [strategy-stakes-review](../strategy-stakes-review/) instead
- The artifact has no factual claims (a pure brainstorming note or speculative framing)
- You want the operator's own source-finding work done for them — this skill names the gap; the operator either finds the source or weakens the claim

**Anti-inputs (out of scope for this skill):**
- Structural critique (out of scope; that is the Skeptic deliberator)
- Voice and register critique (out of scope; that is the Voice & Identity deliberator)
- Strategic alignment review (out of scope; that is the Strategy & Stakes deliberator)
- Doing the source-finding (this skill names gaps; operator closes them)
- Verdict synthesis (run [adjudicator-synthesis](../adjudicator-synthesis/) after at least 2 deliberators)

## Evidence Tier Definitions

The skill uses a standard 6-tier scale:

| Tier | What | Example |
|------|------|---------|
| **T1** | Primary source, verified link, recent | Anthropic blog post, dated, with stable URL |
| **T2** | Primary source, verified, slightly older or institutional | Microsoft earnings call, SEC filing |
| **T3** | Secondary reputable, verified | Reuters article citing T1 source |
| **T4** | Operator's own prior work, public | Operator's own published spec, repo, or paper |
| **T5** | Operator claim, plausible, not externally verifiable | "I ran this with three teams" with no link |
| **T6** | Inferred / asserted / pattern-matched | "Most PM frameworks fall apart" with no citation |

**Any T5 or T6 claim used to support a strong conclusion is a calibration risk.** Acknowledge inline ("in my experience" or "in three pilots with self-reporting teams") or supply external support.

## Standalone vs Composed Use

| Mode | What you get | When to pick this mode |
|---|---|---|
| **Standalone Evidence** | Per-claim tier map + calibration issues + P11/P17/P54 flags | Fast ad-hoc evidence audit on a single artifact. Lowest cost. |
| **Evidence + Skeptic** | Substance + claim-support triangulation | When the artifact has both load-bearing arguments AND many factual claims. Most common pairing for analyses. |
| **Evidence + 3 others + Adjudicator** | Full Council review with SHIP/REVISE/HOLD verdict | Tier-1 artifact gating via interactive skill loading |
| **Full Council via CLI/MCP** | Parallel deliberation + 2-round cross-read rebuttal + JSONL audit | Automated pre-ship gates. Use `python -m agent_council review path/to/artifact.md --tier=1` |

## Method

### Step 1: Extract every load-bearing claim

Walk the artifact. A load-bearing claim is one the argument's spine rests on. Filler ("agentic systems are interesting") is not load-bearing. **Numerical claims, named systems, attributions, and causal claims usually are.**

Quote each claim verbatim (≤30 words). Do not paraphrase — paraphrase corrupts the tier assignment.

### Step 2: Assign a tier per claim

For each claim, ask: what tier of evidence actually supports this? Use the T1-T6 scale above. **Tier assignment requires reading the underlying support, not inferring from how confident the prose sounds.**

- If the claim cites a verified primary source with a stable link → T1 or T2 depending on recency
- If the claim cites a reputable secondary source that references T1 → T3
- If the claim references the operator's own public prior work → T4
- If the claim is "I did X" or "we ran Y" with no link → T5
- If the claim is a sweeping generalization with no citation → T6

### Step 3: Assess status per claim

For each claim, classify status:

- `verified` — tier and support match; nothing to fix
- `underspecified` — claim is plausible but missing the link/source that would make it externally verifiable
- `asserted_without_evidence` — claim is asserted with high confidence but support is weak or absent
- `mis-tiered` — claim is presented as if it were a higher tier than the actual evidence base

For each underspecified or mis-tiered claim, name the fix: link the source, or hedge the confidence to match the tier.

### Step 4: Find calibration issues

Calibration goes both directions:

- **Over-claiming** (most common): a T5 anecdote presented as a T2 generalizable finding. "Three teams reported X" → "the protocol causes X."
- **Under-claiming** (also a failure): a verified T2 claim hedged with "perhaps." Honesty theater. Stop hedging what you actually know.

Flag both directions explicitly.

### Step 5: Check P11, P17, P54 patterns

- **P11 citation-as-decoration:** A citation that does not actually support the claim. Read the source-as-cited, not just the citation marker.
- **P17 pile-of-anecdotes-as-evidence:** Three or four anecdotes presented as a finding. Three teams ≠ a study.
- **P54 unverifiable-single-source:** A claim sourced only to "I heard from X" or "I saw on Twitter" with no archived reference.

### Step 6: Set the block flags

`would_block: true` if any of: (a) a load-bearing claim is T5 or T6 without acknowledgment, (b) calibration is inverted (high confidence on weak evidence), (c) P11/P17/P54 fires on a load-bearing claim.

`irreducible: true` only if the evidence base is so thin the artifact cannot make its claims at all — only restructure to weaker claims. Rare.

### Step 7: Emit the structured output

Return a single fenced JSON block matching the Round 1 schema. Score on 1-5: 1 = every load-bearing claim is unsourced or mis-tiered, 5 = every load-bearing claim is correctly tiered and well-calibrated.

## Output Format

Single fenced JSON block. Round 1 schema:

```json
{
  "role": "evidence",
  "round": 1,
  "score": 1,
  "claim_tier_map": [
    {"claim": "Stratum priced $7,500 standard", "tier": "T5", "status": "underspecified", "fix": "Add a source link to the canonical Stratum spec entry, or remove the number."},
    {"claim": "Three teams reported cycle time dropped by half", "tier": "T5", "status": "asserted_without_evidence", "fix": "Either link the pilot reports or hedge: 'Three self-reporting pilot teams.'"},
    {"claim": "Microsoft Copilot grew 60M->150M MAU", "tier": "T4", "status": "verified", "fix": null}
  ],
  "calibration_issues": [
    "Three-team sample stated as generalizable finding — should be hedged.",
    "Pricing claim asserted with high confidence but no source — invert to T5 acknowledgment."
  ],
  "p11_p17_p54_flags": [
    "P17: pile of three anecdotes presented as a finding"
  ],
  "would_block": false,
  "irreducible": false,
  "notes": "≤2 sentences on overall evidence posture"
}
```

Round 2 (with prior R1 critiques in context):

```json
{
  "role": "evidence",
  "round": 2,
  "score": 1,
  "concessions": ["Skeptic raised the same T5 pricing gap — agreed."],
  "escalations": ["..."],
  "would_block": false,
  "irreducible": false
}
```

## Worked Example

**Input artifact (excerpt):**
> Stratum is priced at $7,500 for standard, $12,500 for extended. I have run it with three teams. All three reported cycle time dropped by half. Most PM frameworks fall apart in agentic systems.

**Evidence & Calibration R1 output:**

```json
{
  "role": "evidence",
  "round": 1,
  "score": 3,
  "claim_tier_map": [
    {"claim": "Stratum priced $7,500/$12,500", "tier": "T5", "status": "underspecified", "fix": "Link the Stratum spec entry or pricing page."},
    {"claim": "Three teams reported 2x cycle-time drop", "tier": "T5", "status": "asserted_without_evidence", "fix": "Either link the three pilot reports or hedge as 'three self-reporting pilots.'"},
    {"claim": "Most PM frameworks fall apart in agentic systems", "tier": "T6", "status": "asserted_without_evidence", "fix": "Cite at least one specific framework failure, or weaken to 'in my experience, most...'"}
  ],
  "calibration_issues": [
    "Three-team finding stated as generalizable; needs explicit confound discussion.",
    "Sweeping claim about PM frameworks asserted with no support — high confidence on T6 evidence."
  ],
  "p11_p17_p54_flags": ["P17: three anecdotes presented as evidence"],
  "would_block": true,
  "irreducible": false,
  "notes": "One T5 pricing claim and one T6 sweeping claim, both load-bearing. Block to revise."
}
```

## Failure Modes (in Evidence & Calibration's own output)

1. **Tier-by-vibes.** Calling a claim "Tier 2" without checking the actual source. Tier assignment requires reading the underlying support, not inferring from how confident the prose sounds.
2. **Confusing rhetoric with evidence.** "The author writes confidently, therefore the claim is well-supported" is the inverted failure. Confidence is not evidence.
3. **Missing the inverted miscalibration.** Under-claiming is also a calibration failure. If a verified T2 claim is hedged with "perhaps," that is honesty theater. Flag both directions.
4. **Failing to catch P11.** A claim with a citation that does not actually support the claim is worse than a claim with no citation. Read the source-as-cited.
5. **R2 just lifting Skeptic's framing.** If the Skeptic surfaced the same evidence gap and your R2 concedes without contributing the tier assignment, you have not earned your seat on the panel.

## Communication Style (when Evidence & Calibration narrates findings)

- "Claim 1 is T5 — operator assertion, plausible, no link. Fix: source it or hedge it."
- "Claim 3 is T6 — sweeping generalization with no support. Either narrow the claim or supply a citation."
- "The artifact treats three self-reporting teams as a finding. That is P17. Flag."
- "Calibration is inverted on paragraph 5 — verified T2 claim hedged with 'perhaps.' Stop hedging what you know."
- "R2: agreed with Skeptic on the pricing gap; my framing keeps the tier label, theirs keeps the failure-mode label. Both stand."

## Anti-Pattern Caught

"The piece reads confidently, therefore the claims are supported." Confidence is not evidence. Evidence & Calibration exists precisely to catch the cases where a polished, confident-sounding artifact rests on T5/T6 claims that the author has not externally verified. The audit is per-claim; the polish does not transfer.

## Related

- [skeptic-review](../skeptic-review/) — structural critique. Compose with Evidence & Calibration to triangulate on weak-evidence claims that are also structurally load-bearing.
- [voice-identity-review](../voice-identity-review/) — line-level voice violations. Compose when the artifact is both claim-dense AND public-facing.
- [strategy-stakes-review](../strategy-stakes-review/) — goal-fit and opportunity-cost check.
- [adjudicator-synthesis](../adjudicator-synthesis/) — synthesis only; not a deliberator. Consumes 2+ deliberator outputs to produce SHIP/REVISE/HOLD verdict. Do not load standalone on an artifact.
- Full Council via CLI: `python -m agent_council review path/to/artifact.md --tier=1`
