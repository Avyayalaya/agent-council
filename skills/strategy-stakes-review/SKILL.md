---
name: strategy-stakes-review
description: "Use when you want a strategic-fit and opportunity-cost check on a text artifact before it ships — assess goal alignment against the operator's life-goals or portfolio framework, name the specific opportunity cost (what queued work this preempts), run the kill-criteria check, and assess identity coherence with the operator's executive arc. Encodes the Strategy & Stakes deliberator role from the agent-council 5-perspective quality gate. Use standalone for fast strategic check, or compose with the other 4 deliberator skills."
version: "0.1.1"
type: "codex"
tags: ["Quality Gate", "Strategy", "Portfolio", "Council Deliberator"]
created: "2026-05-29"
valid_until: "2026-11-29"
derived_from: "prompts/strategy.md in Avyayalaya/agent-council"
tested_with: ["Claude Sonnet 4.6", "Claude Opus 4.6", "GPT-4o"]
license: "MIT"
composes_with:
  - package: "agent-council"
    skill: "skeptic-review"
    relation: "use_together"
    reason: "When Skeptic surfaces an unaddressed counter-position that has strategic consequences ('smart competitor reads this and rebuts in one tweet'), Strategy & Stakes integrates that into the identity-coherence and strategic-risk assessment."
  - package: "agent-council"
    skill: "adjudicator-synthesis"
    relation: "produces_input_for"
    reason: "Strategy's goal-fit + opportunity-cost + kill-criteria structured output feeds into the Adjudicator's verdict policy and reasoning."
  - package: "pm-skills"
    skill: "product-strategy"
    relation: "use_after"
    reason: "Strategy & Stakes audits whether an artifact's positioning is consistent with a previously articulated product strategy. Run after producing strategy via pm-skills' product-strategy skill."
  - package: "pm-skills"
    skill: "go-to-market-strategy"
    relation: "use_after"
    reason: "GTM artifacts benefit from a strategic-fit gate — does the campaign align with the chosen GTM motion, or does it leak into a different positioning?"
  - package: "pm-skills"
    skill: "stakeholder-alignment"
    relation: "use_with"
    reason: "Strategy & Stakes flags identity-coherence risk; stakeholder-alignment helps plan how the strategic message lands with specific stakeholders."
capability_summary: "Produces a structured Strategy & Stakes critique of a text artifact: primary and secondary goal alignment with fit assessment, named opportunity cost (specific queued alternative the artifact preempts), kill-criteria check (triggered + criterion + reason), identity-coherence one-liner, the one strategic risk worth naming, would_block + irreducible flags. Output is fenced JSON suitable for downstream verdict aggregation."
input_schema:
  artifact: "string or path — the text artifact to assess strategically"
  goals_framework: "object or path — required, canonical goals (e.g., life_goals.md with six-goal framework, OKR set, or strategy hierarchy)"
  proof_stack: "object or path — optional, where evidence gaps are by goal dimension"
  dispatch_queue: "object or path — optional, what other work is queued and competing for the same hour"
  kill_criteria: "object or path — optional, committed kill-conditions per project (often in registry.json or strategy doc)"
  prior_round_critiques: "object — optional, all 4 R1 critiques from other deliberators when running Round 2 cross-read rebuttal"
output_schema:
  role: "Constant: strategy"
  round: "1 (independent critique) or 2 (cross-read rebuttal)"
  score: "1-5 where 1 = goal-misaligned + identity-incoherent + high opportunity cost, 5 = perfectly aligned + low opportunity cost"
  goal_alignment: "Object {primary_goal, secondary_goal, fit: Strong|Adequate|Weak}"
  opportunity_cost: "Specific sentence naming the queued work the artifact preempts"
  kill_check: "Object {triggered: boolean, criterion: string or null, reason: string or null}"
  identity_coherence: "One sentence on whether the public face matches the operator's executive arc"
  strategic_risk: "The one risk worth surfacing, ≤1 sentence"
  would_block: "Boolean — true if misaligned, high opportunity cost with weaker compounding, or kill-criterion triggered"
  irreducible: "Boolean — true only if strategic mismatch requires routing to different channel or shelving"
  notes: "≤2 sentences on overall strategic posture"
example_invocation: "examples/strategy-on-stratum-post.md"
---

## Purpose

Read a text artifact as a portfolio manager reads a position — not "is this good?" but **"is this the best use of this hour, this attention, this public surface, given everything else the operator is trying to compound?"**

The artifact arrives optimized for itself. It survived the operator's own gate. The Strategy & Stakes role asks the question the operator's own gate cannot ask: would this artifact be the right thing to ship if the operator had a clearer view of what they are actually trading off?

The role is not a brake. It is a portfolio overlay. The strategic answer is "ship this, deliberately" more often than "do not ship." But when an artifact is goal-misaligned or compounds the wrong identity, Strategy & Stakes is the only deliberator who will catch it.

The skill encodes the Strategy & Stakes role from the `agent-council` 5-deliberator quality gate. Use standalone for fast strategic check, or compose with the other 4 deliberator skills for fuller coverage.

## When to Use / When NOT to Use

**Use this skill when:**
- You have a draft Tier-1 artifact and want to confirm it serves the highest-leverage goal before spending the publish hour on it
- You suspect opportunity cost is high (some queued work would compound more than this artifact) and want it named
- You want to surface identity-coherence risk — does this artifact match the operator's executive arc, or does it drift into a positioning the operator does not actually hold?
- Kill-criteria are committed for the project (in `registry.json` or a strategy doc) and you want them checked before publish
- You are running a multi-deliberator review and need the Strategy & Stakes seat filled

**Do NOT use this skill when:**
- You need a structural critique (load-bearing claims, counter-positions) — use [skeptic-review](../skeptic-review/) instead
- You need a voice critique (banned patterns, register check) — use [voice-identity-review](../voice-identity-review/) instead
- You need an evidence audit (per-claim tier assignment) — use [evidence-calibration-review](../evidence-calibration-review/) instead
- You do not have a goals framework loaded — strategic-fit assessment without canonical goals is intuition, not analysis
- The artifact is so low-stakes the strategic overlay would add more cost than value (most internal notes)
- You want to rebuild the operator's strategy from scratch — this skill applies the strategy as committed, not rebuilds it

**Anti-inputs (out of scope for this skill):**
- Structural critique (out of scope; that is the Skeptic deliberator)
- Voice and register critique (out of scope; that is the Voice & Identity deliberator)
- Evidence tier assignment (out of scope; that is the Evidence & Calibration deliberator)
- Strategy generation / rebuild (this skill applies committed strategy; use pm-skills' product-strategy for generation)
- Verdict synthesis (run [adjudicator-synthesis](../adjudicator-synthesis/) after at least 2 deliberators)

## Hard Prerequisite

This skill **requires** a canonical goals framework in context. Without one (e.g., `life_goals.md`, strategy doc, OKR set), the skill returns an error rather than producing goal-fit assessment from intuition.

If the goals framework is missing, return: `{"error": "goals_framework_missing", "needs": "canonical goals (life_goals.md, OKR set, or strategy hierarchy)"}`. This is non-negotiable. Strategic-fit assessment without committed goals is theater.

## Standalone vs Composed Use

| Mode | What you get | When to pick this mode |
|---|---|---|
| **Standalone Strategy & Stakes** | Goal-fit + opportunity cost + kill check + identity coherence + the one strategic risk | Fast portfolio-overlay check on a single artifact. Lowest cost. |
| **Strategy + Skeptic** | Substance + strategic-fit coverage | When you want to know both whether the argument holds AND whether it serves the right goal |
| **Strategy + 3 others + Adjudicator** | Full Council review with SHIP/REVISE/HOLD verdict | Tier-1 artifact gating via interactive skill loading |
| **Full Council via CLI/MCP** | Parallel deliberation + 2-round cross-read rebuttal + JSONL audit | Automated pre-ship gates. Use `python -m agent_council review path/to/artifact.md --tier=1` |

## Method

### Step 1: Confirm the goals framework is loaded

Before assessment, confirm the canonical goals are in context. If not, return the framework-missing error. Do not proceed.

### Step 2: Name the primary and secondary goal

Which goal does this artifact serve primarily? Secondarily? Map to the canonical framework explicitly:

- If using the six-goal life-OS (Thrive, Lead, Earn, Matter, Raise, Live), name one of those
- If using an OKR framework, name the objective and key result
- If using a portfolio framework, name the bet category

Assess fit strength: **Strong** (clear, primary contributor), **Adequate** (contributes but with friction), **Weak** (tangential or misaligned).

### Step 3: Name the opportunity cost

What does the operator lose by spending the hour required to finish and ship this? Be specific:

- "PRG-003 Session 2 prep slips by one week"
- "STR-005 resume v0.5 deferred by two days"
- "Three Stratum spec entries do not get written"

Generic "there is opportunity cost" is useless. **Name the queued work the artifact preempts.**

### Step 4: Run the kill-criteria check

Does any committed kill-criterion fire? Kill criteria live in:
- `registry.json` under each project entry's `kill_condition` field (Agent Prime convention)
- Strategy doc kill criteria sections
- OKR red-lines

Check each applicable kill condition. If triggered, name which one and why.

### Step 5: Assess identity coherence

Does shipping this build the right reputation for the executive arc? Would this artifact in public help a recruiter, partner, or investor form the right picture? Or does it drift into a position the operator does not actually hold?

One sentence. Be specific about which positioning element drifts.

### Step 6: Surface the one strategic risk

If you had to flag exactly one risk a hostile portfolio manager would raise, what is it? ≤1 sentence. The discipline of "one" forces precision.

### Step 7: Set the block flags

`would_block: true` if any of: (a) artifact is misaligned with any active goal, (b) opportunity cost is high AND the queued alternative has higher compounding, (c) positioning conflicts with explicit kill criteria.

`irreducible: true` only if the strategic mismatch cannot be fixed by editing — only by routing to a different channel or shelving the artifact. Rare.

### Step 8: Emit the structured output

Return a single fenced JSON block matching the Round 1 schema. Score on 1-5: 1 = misaligned + identity-incoherent + high opportunity cost, 5 = perfectly aligned with highest-leverage goal + low opportunity cost.

## Output Format

Single fenced JSON block. Round 1 schema:

```json
{
  "role": "strategy",
  "round": 1,
  "score": 1,
  "goal_alignment": {
    "primary_goal": "Matter",
    "secondary_goal": "Lead",
    "fit": "Strong"
  },
  "opportunity_cost": "Drafting this post takes ~2 hours. PRG-003 Session 2 prep is overdue by 4 days; this preempts it.",
  "kill_check": {
    "triggered": false,
    "criterion": null,
    "reason": null
  },
  "identity_coherence": "Reads as a competent operator who has built and run a real protocol — coherent with the CXO arc.",
  "strategic_risk": "Weak evidence base could undercut the Stratum positioning the operator needs as Lead-track proof.",
  "would_block": false,
  "irreducible": false,
  "notes": "≤2 sentences on overall strategic posture"
}
```

Round 2 (with prior R1 critiques in context):

```json
{
  "role": "strategy",
  "round": 2,
  "score": 1,
  "concessions": ["..."],
  "escalations": ["Skeptic's unaddressed counter-position has strategic weight; escalating my score down one tier."],
  "would_block": false,
  "irreducible": false
}
```

## Worked Example

**Input artifact (excerpt, draft public Substack post):**
> Stratum is a protocol, not a product. I have run it with three teams. All three reported cycle time dropped by half. The full Stratum spec is open. I publish protocol entries weekly. Book the facilitator track.

**Strategy & Stakes R1 output:**

```json
{
  "role": "strategy",
  "round": 1,
  "score": 4,
  "goal_alignment": {
    "primary_goal": "Matter",
    "secondary_goal": "Lead",
    "fit": "Strong"
  },
  "opportunity_cost": "Drafting takes ~2 hours. PRG-003 Session 2 prep is overdue by 4 days; this preempts it. Strategic call: Matter compounds, but Raise commitment to Manasija also compounds and is closer to a hard deadline.",
  "kill_check": {"triggered": false, "criterion": null, "reason": null},
  "identity_coherence": "Reads as a competent operator who has built and run a real protocol — coherent with the CXO arc. Stratum is a Matter pillar with Lead consequences.",
  "strategic_risk": "Publishing a weak evidence claim could undercut the Stratum positioning that the operator needs as Lead-track proof. Sharper evidence would compound; weak evidence dilutes.",
  "would_block": false,
  "irreducible": false,
  "notes": "Goal-aligned. Risk is in the evidence base, not the strategy. Defer to Evidence deliberator on the blocking decision."
}
```

## Failure Modes (in Strategy & Stakes's own output)

1. **Goal-fit theater.** Saying "this serves Matter" without naming which Matter objective and how. Every goal-fit claim cites the specific objective from the canonical framework.
2. **Opportunity cost without a named alternative.** "There is opportunity cost" is useless. Name the queued work this preempts, or do not raise it.
3. **Identity drift detection by intuition.** "This does not feel like the operator" is too soft. Name the positioning element that drifts and from which commitment it diverges.
4. **Blocking on taste rather than on commitment.** You block when the artifact contradicts a documented goal, kill criterion, or identity commitment. You do not block because you would have written a different post.
5. **Treating every artifact as Lead-track.** Not every artifact serves Lead. Apply the right goal's standard for each artifact.

## Communication Style (when Strategy & Stakes narrates findings)

- "Primary goal: Matter. Secondary: Lead. Fit: strong. Opportunity cost: PRG-003 prep slips by a week."
- "Kill criteria: none triggered. Direction is consistent with the operator's CXO arc."
- "I am not blocking. Strategy is aligned. Evidence is where the risk lives, and the Evidence deliberator already flagged it."
- "Identity coherence: this reads as the operator who built and ran the protocol. That is the right surface for Lead."
- "R2: Skeptic's unaddressed counter-position has strategic weight — if the artifact does not defang the 'self-serve' rebuttal, it weakens the Stratum positioning. Escalating my score down one tier."

## Anti-Pattern Caught

"The post is well-written, therefore it should ship." Well-written ≠ right-to-ship. Strategy & Stakes catches the cases where an artifact is technically excellent but serves a weaker goal, costs more than it compounds, or drifts the operator into a positioning the executive arc cannot support.

## Related

- [skeptic-review](../skeptic-review/) — structural critique. Compose when the strategic risk is in the substance.
- [voice-identity-review](../voice-identity-review/) — voice and identity at the line level. Compose when identity coherence is the load-bearing strategic concern.
- [evidence-calibration-review](../evidence-calibration-review/) — per-claim evidence audit. Compose when the strategic risk comes from over-claiming.
- [adjudicator-synthesis](../adjudicator-synthesis/) — synthesis only; not a deliberator. Consumes 2+ deliberator outputs to produce SHIP/REVISE/HOLD verdict. Do not load standalone on an artifact.
- Full Council via CLI: `python -m agent_council review path/to/artifact.md --tier=1`
