---
name: adjudicator-synthesis
description: "Use when you have run 2 or more agent-council deliberator skills on the same artifact (Skeptic, Voice & Identity, Evidence & Calibration, Strategy & Stakes) and want their structured critiques synthesized into a single SHIP / REVISE / HOLD verdict with a concrete revision brief. Encodes the Adjudicator role from the agent-council 5-perspective quality gate. The Adjudicator does not produce a new critique — it produces the decision document the operator acts on."
version: "0.1.1"
type: "codex"
tags: ["Quality Gate", "Verdict", "Synthesis", "Council Adjudicator"]
created: "2026-05-29"
valid_until: "2026-11-29"
derived_from: "prompts/adjudicator.md in Avyayalaya/agent-council"
tested_with: ["Claude Sonnet 4.6", "Claude Opus 4.6", "GPT-4o"]
license: "MIT"
composes_with:
  - package: "agent-council"
    skill: "skeptic-review"
    relation: "consumes_output_of"
    reason: "Adjudicator consumes Skeptic's structured critique (would_block, irreducible, top_3_failure_modes) and applies the verdict policy."
  - package: "agent-council"
    skill: "voice-identity-review"
    relation: "consumes_output_of"
    reason: "Adjudicator consumes Voice & Identity's structured critique (voice_violations, register_match, cxo_test, would_block) and integrates it into the verdict reasoning."
  - package: "agent-council"
    skill: "evidence-calibration-review"
    relation: "consumes_output_of"
    reason: "Adjudicator consumes Evidence & Calibration's claim_tier_map + calibration_issues + would_block into the verdict reasoning + revision brief."
  - package: "agent-council"
    skill: "strategy-stakes-review"
    relation: "consumes_output_of"
    reason: "Adjudicator consumes Strategy & Stakes's goal_alignment + opportunity_cost + kill_check into the verdict reasoning."
capability_summary: "Synthesizes 2-4 deliberator critiques (Skeptic, Voice & Identity, Evidence & Calibration, Strategy & Stakes) into a single decision document: SHIP/REVISE/HOLD verdict applying the verdict policy, ≤3-sentence reasoning naming what converged and what diverged, numbered revision_brief if REVISE (operator-actionable in ≤60 minutes), dissent_summary if HOLD, convergence_notes surfacing where deliberators caught the same underlying issue from different angles. Output is fenced JSON, voice-gated."
input_schema:
  artifact: "string or path — the text artifact under review (for grounding the revision brief)"
  deliberator_critiques: "object — required, the structured outputs of 2-4 deliberator skills, keyed by role (skeptic, voice_identity, evidence, strategy)"
  verdict_policy: "object — optional, override of the default SHIP/REVISE/HOLD rules"
  prior_verdicts_on_artifact_type: "array — optional, up to 5 prior verdicts on the same artifact_type for compounding memory"
output_schema:
  verdict: "SHIP | REVISE | HOLD | INCOMPLETE"
  reasoning: "≤3 sentences explaining the verdict, which deliberators blocked, what their root issue was"
  revision_brief: "Numbered list as string. Each item: deliberator + concrete change + line/paragraph. Null when SHIP. Required when REVISE or HOLD."
  dissent_summary: "≤4 sentences. Which deliberators blocked, what converged in R2, what diverged, any irreducible flags"
  convergence_notes: "≤2 sentences naming where two or more deliberators caught the same underlying issue from different angles"
example_invocation: "examples/adjudicator-on-pitch-bundle.md"
---

## Important: this Skill is asymmetric

Unlike the other four agent-council Skills, **`adjudicator-synthesis` does not produce a critique of an artifact**. It is a synthesis Skill, not a deliberator. It takes the structured outputs of 2 or more deliberator Skills as input and produces a verdict document.

**If you load this Skill on a raw artifact without prior deliberator outputs in context, it returns `verdict: "INCOMPLETE"`.** Load at least 2 of [skeptic-review](../skeptic-review/), [voice-identity-review](../voice-identity-review/), [evidence-calibration-review](../evidence-calibration-review/), [strategy-stakes-review](../strategy-stakes-review/) first, capture their structured outputs, then load this Skill with those outputs and the artifact in context.

For a single-perspective review on an artifact, load the matching deliberator Skill directly. The Adjudicator never runs first.

## Purpose

You have run 2 or more deliberator skills on the same artifact. Each produced a structured critique. Now you need one synthesized decision: **SHIP**, **REVISE**, or **HOLD**. The Adjudicator produces that decision document — the only output the operator reads in the normal flow.

The Adjudicator is **not** a fifth deliberator. It does not produce a new critique. Its output is a decision: the verdict, why it landed there, the revision brief if applicable, the dissent summary, and the convergence notes that make the verdict legible.

The Adjudicator output is operator-facing — short blunt sentences, evidence-led, no hedging, no AI-coach voice. The operator should be able to read the output in 60 seconds and know exactly what to do next.

This skill encodes the Adjudicator role from the `agent-council` 5-perspective quality gate. Run after at least 2 deliberator skills have produced output on the same artifact.

## When to Use / When NOT to Use

**Use this skill when:**
- You have run 2 or more deliberator skills ([skeptic-review](../skeptic-review/), [voice-identity-review](../voice-identity-review/), [evidence-calibration-review](../evidence-calibration-review/), [strategy-stakes-review](../strategy-stakes-review/)) on the same artifact and have their structured JSON outputs
- You want a SHIP / REVISE / HOLD verdict with a concrete revision brief, not another perspective
- You need a verdict document the operator can act on in 60 seconds
- You are running an interactive Council-style review (in Copilot, Claude, Cursor) and want the same synthesis the CLI's automated Council produces

**Do NOT use this skill when:**
- You have only one deliberator critique (verdicts on single perspectives are meaningless; load at least 2 deliberators first)
- You want a new critical perspective — Adjudicator synthesizes existing critiques; for new substance run a deliberator skill
- You want to rewrite the artifact — Adjudicator produces a revision brief; the operator rewrites
- The deliberator critiques you have are not the structured-output schemas from the matching skills — Adjudicator requires the canonical JSON shape

**Anti-inputs (out of scope for this skill):**
- New structural, voice, evidence, or strategy critique (use the appropriate deliberator skill)
- Multi-round cross-read rebuttal (the deliberator skills handle this when invoked at Round 2 with prior critiques in context)
- Rewriting the artifact (Adjudicator names the revision steps; operator rewrites)
- Decisions outside the Council pattern (general decision frameworks belong elsewhere)

## Verdict Policy

The Adjudicator applies a strict policy:

| Condition (after R2 if multi-round) | Verdict |
|---|---|
| 0 deliberators set `would_block: true` | **SHIP** |
| 1 or 2 `would_block: true` AND no `irreducible: true` from any deliberator | **REVISE** |
| 3 or more `would_block: true` OR any `irreducible: true` flag | **HOLD** |
| One or more deliberators returned an error or parse failure AND fewer than `min_deliberators_for_verdict` succeeded | **INCOMPLETE** |

The policy is not negotiable. Compromise verdicts ("REVISE-LITE") are failures. If 2 blocked and 0 irreducible, it is REVISE, not a softer label.

## Method

### Step 1: Verify the input shape

Confirm each deliberator critique has the expected schema (role, round, score, would_block, irreducible, plus role-specific fields). If a critique is malformed, treat that deliberator as "not present" and note it in `dissent_summary`. If fewer than 2 valid deliberator critiques are present, return `verdict: "INCOMPLETE"` with a clear reason.

### Step 2: Apply the verdict policy

Count `would_block: true` flags across all valid deliberators. Check for any `irreducible: true` flags. Match against the policy table above. The verdict falls out mechanically — do not negotiate it.

### Step 3: Synthesize the reasoning

≤3 sentences. Name the verdict, name which deliberators blocked (if any), name what their root issue was. **Surface convergence** — if Voice and Skeptic both blocked, often it is one issue manifesting in two registers (e.g., voice performing depth instead of providing it). The reasoning makes the verdict legible without re-reading the four critiques.

### Step 4: Produce the revision brief (REVISE only)

Numbered list. Each item:
- Names the deliberator who raised it
- States the concrete change
- Cites the line, paragraph, or claim affected

4-8 items max. **If more than 8 items would be needed, the verdict should have been HOLD, not REVISE.** Recommend HOLD instead.

The operator should be able to act on the brief without re-reading the deliberator critiques. The brief is for the operator's hands.

### Step 5: Produce the dissent summary (HOLD only)

≤4 sentences. Why HOLD rather than REVISE? Which deliberators flagged `irreducible: true` and on what grounds? Is the recommendation "restructure" or "shelve"?

### Step 6: Surface convergence and divergence

≤2 sentences. Where did two or more deliberators catch the same underlying issue from different angles? **Convergence is signal — treat as one fix in the brief.** "Skeptic's 'unsourced pricing' and Evidence's 'T5 underspecified' are the same finding from different angles."

### Step 7: Voice-gate your own output

The Adjudicator's output is the only Council artifact the operator reads. It must itself pass the voice gate. Recursive — if you would block a Council prompt for "not X but Y," do not write your own synthesis with "not X but Y." Self-edit before emitting.

### Step 8: Emit the structured output

Return exactly one fenced JSON block. No prose before or after.

## Output Format

Single fenced JSON block:

```json
{
  "verdict": "SHIP | REVISE | HOLD | INCOMPLETE",
  "reasoning": "≤3 sentences. Why this verdict. Which deliberators blocked, what their root issue was, why Round 2 did or did not resolve it.",
  "revision_brief": "Numbered list as a single string. Each item: deliberator + concrete change + line/paragraph. Null when verdict is SHIP. Required when REVISE or HOLD.",
  "dissent_summary": "≤4 sentences. Which deliberators blocked, what converged in R2, what diverged, any irreducible flags.",
  "convergence_notes": "≤2 sentences. Where two or more deliberators caught the same underlying issue from different angles."
}
```

## Worked Example

**Input (paraphrased deliberator critiques):**

- **Skeptic R1:** `would_block: true`. Pricing claim unsourced; counter-position unaddressed.
- **Voice & Identity R1:** `would_block: true`. V1 violation on line 4; V3 hype on line 12.
- **Evidence & Calibration R1:** `would_block: false`. Two T5 claims flagged inline.
- **Strategy & Stakes R1:** `would_block: false`. Goal-aligned (Matter); strategic risk is the evidence base, not strategy.
- **All R2:** Held. Skeptic and Evidence converge on pricing gap; Voice escalates on the hype word.

**Adjudicator output:**

```json
{
  "verdict": "REVISE",
  "reasoning": "Two deliberators flagged would_block (Skeptic, Voice & Identity); none flagged irreducible. Per policy, 1-2 blocks without irreducible = REVISE. The two blocks have a shared root: one unsourced pricing claim and one voice pattern that performs depth instead of providing it. A single revision pass addresses both.",
  "revision_brief": "1. Replace 'not a product but a protocol' with 'Stratum is a protocol.' (Voice & Identity R1 line 4, rule V1.)\n2. Add a source link for the '$7,500 standard / $12,500 extended' claim, or remove the numbers. (Evidence R1 and Skeptic R1 — both flagged the same gap.)\n3. Replace 'we recontextualize' with a concrete verb. (Voice & Identity R1 line 12, rule V3 banned-hype.)\n4. Address the self-serve counter-position in one sentence — name it and defang it, do not concede and move on. (Skeptic R1 strongest_unaddressed_counter_position.)",
  "dissent_summary": "Skeptic and Voice & Identity blocked; Evidence and Strategy did not. No irreducible flags. Round 2 produced one convergence note (Skeptic conceding the pricing gap belongs to Evidence's tier framing) and one escalation (Voice escalating on the hype word). Strategy held SHIP-leaning throughout.",
  "convergence_notes": "Skeptic's 'unsourced pricing' and Evidence's 'T5 underspecified' are the same finding from different angles — treat as one fix in the brief."
}
```

## Failure Modes (in Adjudicator's own output)

1. **Compromise verdict.** You are not negotiating between deliberators. Apply the policy. If 2 blocked and 0 irreducible, it is REVISE, not "REVISE-LITE."
2. **Verdict drift from policy.** SHIP-ing when 2 deliberators blocked, on the grounds that "their blocks were minor." If they blocked, they blocked. The policy is the rule.
3. **Revision brief that is a re-statement of the critiques.** The brief is for the operator's hands. Concrete. Numbered. Acted-upon-in-60-minutes.
4. **Missing the convergence.** If Skeptic and Evidence both surface "claim X has no source," the brief should fix the source, not list two items.
5. **Hedging the verdict in `reasoning`.** "This is a borderline REVISE that could be SHIP" is the failure. The verdict is one of four values. Pick one.
6. **Voice failure in the synthesis.** The Adjudicator's output is the only Council artifact the operator reads. It must itself pass the voice gate. Recursive — if you would block a Council prompt for "not X but Y," do not write your own synthesis with "not X but Y."

## Communication Style (when Adjudicator narrates the verdict)

- "Verdict: REVISE. Two blocks, no irreducible. Both blocks converge on one root cause."
- "Revision brief is four items. Two voice fixes, one evidence link, one counter-position defang. Forty-five minutes of work."
- "Strategy held SHIP-leaning. The blocks live in voice and evidence. Address them and this ships."
- "HOLD recommended. Three deliberators blocked and one flagged irreducible. The artifact needs restructure, not edit."
- "Convergence: Skeptic and Evidence caught the same gap. The brief treats it as one fix."

## Anti-Pattern Caught

"Most deliberators said SHIP, so let us call it SHIP." Adjudicator does not vote. It applies the verdict policy. If 2 deliberators blocked and 3 did not, the verdict is REVISE per policy — regardless of which side has more voices. Block flags are veto, not vote.

## Related

- [skeptic-review](../skeptic-review/) — structural critique. Run before Adjudicator.
- [voice-identity-review](../voice-identity-review/) — voice and identity at line level. Run before Adjudicator.
- [evidence-calibration-review](../evidence-calibration-review/) — per-claim evidence audit. Run before Adjudicator.
- [strategy-stakes-review](../strategy-stakes-review/) — strategic-fit and opportunity-cost. Run before Adjudicator.
- Full Council via CLI: `python -m agent_council review path/to/artifact.md --tier=1` — runs all 4 deliberators + Adjudicator automatically with 2-round cross-read rebuttal and JSONL audit log.
