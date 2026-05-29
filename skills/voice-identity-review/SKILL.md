---
name: voice-identity-review
description: "Use when you want a line-level voice and identity audit on a text artifact before it ships — surface specific voice-rule violations (banned patterns, hype words, register mismatches), apply the CXO test, and check identity coherence with the operator's voice corpus and persona DNA. Encodes the Voice & Identity deliberator role from the agent-council 5-perspective quality gate. Use standalone for fast voice critique, or compose with the other 4 deliberator skills to run a Council-style review without spinning up the full Python CLI."
version: "0.1.1"
type: "codex"
tags: ["Quality Gate", "Voice", "Identity", "CXO Test", "Council Deliberator"]
created: "2026-05-29"
valid_until: "2026-11-29"
derived_from: "prompts/voice_identity.md in Avyayalaya/agent-council"
tested_with: ["Claude Sonnet 4.6", "Claude Opus 4.6", "GPT-4o"]
license: "MIT"
composes_with:
  - package: "agent-council"
    skill: "skeptic-review"
    relation: "use_together"
    reason: "Voice & Identity catches voice-level violations; Skeptic catches structural ones. Often the same root issue manifests in both registers — voice performing depth instead of providing it. Running both surfaces the convergence."
  - package: "agent-council"
    skill: "adjudicator-synthesis"
    relation: "produces_input_for"
    reason: "Voice & Identity's structured output (would_block on banned pattern in load-bearing sentence, CXO test result, register match) feeds into the Adjudicator's verdict policy."
  - package: "pm-skills"
    skill: "executive-writing"
    relation: "use_after"
    reason: "Run voice-identity-review after producing an executive memo via executive-writing — confirms the artifact passes register and CXO checks before it lands in front of VPs."
  - package: "pm-skills"
    skill: "narrative-building"
    relation: "use_after"
    reason: "Narrative drafts often drift into hype register or LinkedIn-influencer voice. Voice & Identity catches these before publish."
  - package: "pm-skills"
    skill: "multi-channel-publishing"
    relation: "use_after"
    reason: "Multi-channel content benefits from per-channel register checks. Voice & Identity assesses channel match (Substack longform vs LinkedIn vs micro-post vs spoken)."
capability_summary: "Produces a structured Voice & Identity critique of a text artifact: per-line voice-rule violations with rule ID and concrete fix, register match assessment for the channel, CXO test result with where-it-breaks, identity fit one-liner, would_block + irreducible flags. Output is fenced JSON suitable for downstream verdict aggregation."
input_schema:
  artifact: "string or path — the text artifact to critique (prose with line numbers when possible)"
  channel: "string — required, e.g., 'substack_longform', 'linkedin_post', 'exec_memo', 'spec', 'spoken_keynote'"
  voice_corpus: "object or path — required, the operator's voice recipe with V1-V15 rules, 9 ingredients, banned patterns, channel registers"
  persona_dna: "object or path — optional, DNA fingerprint extracted from prior artifacts"
  prior_round_critiques: "object — optional, all 4 R1 critiques from other deliberators when running Round 2 cross-read rebuttal"
output_schema:
  role: "Constant: voice_identity"
  round: "1 (independent critique) or 2 (cross-read rebuttal)"
  score: "1-5 where 1 = voice unrecognizable, 5 = voice dialed in"
  voice_violations: "Array of {line, rule, snippet, fix} for each line-level violation"
  register_match: "One of: good, mismatched_channel, mismatched_persona"
  channel_assessment: "Sentence on what register the artifact targets vs what is correct for the channel"
  cxo_test: "Object {pass: boolean, where_it_breaks: string or null}"
  identity_fit: "One sentence on whether this sounds like the operator"
  would_block: "Boolean — true if banned pattern in load-bearing sentence, wrong channel register, or CXO test fail on public-facing piece"
  irreducible: "Boolean — true only if voice is so off it cannot be edited; only redrafted"
  notes: "≤2 sentences on overall voice posture"
example_invocation: "examples/voice-identity-on-pitch-draft.md"
---

## Purpose

Run a line-level voice and identity audit on a text artifact before it ships. The Voice & Identity role reads the artifact against the operator's voice corpus and persona DNA, and surfaces the places where the signal degrades: banned patterns firing, hype words slipping in, register mismatched to the channel, CXO test failing on a public-facing piece.

This skill enforces voice rules at the **line level.** Vague feedback ("this needs a stronger voice") is useless. A voice critique that says "tighten the prose" without naming the line and rule is no different from no critique at all. Every violation cites: line number, rule ID (V1-V15 or banned-pattern from the voice recipe), the offending snippet, the concrete fix.

The skill encodes the Voice & Identity role from the `agent-council` 5-deliberator quality gate. Use standalone for fast voice critique on a draft, or compose with the other 4 deliberator skills to run a Council-style review of a Tier-1 artifact.

## When to Use / When NOT to Use

**Use this skill when:**
- A draft is about to ship externally (Substack, LinkedIn, exec memo, public README, recruiter outreach) and you want voice and register sanity-checked
- You suspect banned-pattern slips ("not X but Y", "recontextualize", "I'm excited to share...", trailing summaries) and want them surfaced explicitly
- A piece needs to pass the CXO test (would a CPO say this in a board meeting? would a CEO own this on stage?) and you want the test applied with specific where-it-breaks
- An artifact targets one channel (e.g., Substack longform) but accidentally writes in another register (e.g., LinkedIn influencer cliche) and you need the channel mismatch named
- You are running a multi-deliberator review and need the Voice & Identity seat filled

**Do NOT use this skill when:**
- You need a structural critique (load-bearing claims, counter-positions, failure modes) — use [skeptic-review](../skeptic-review/) instead
- You need an evidence-tier audit (per-claim tier assignment) — use [evidence-calibration-review](../evidence-calibration-review/) instead
- You need a strategic-fit check (goal alignment, opportunity cost) — use [strategy-stakes-review](../strategy-stakes-review/) instead
- You do not have the operator's voice corpus loaded — voice critique without the corpus is voice critique from training-data priors, which is worse than no critique
- The artifact is a personal note or internal scratch document that does not warrant voice review
- You want to rewrite the artifact — Voice & Identity names violations and fixes; the operator rewrites

**Anti-inputs (out of scope for this skill):**
- Structural critique (out of scope; that is the Skeptic deliberator)
- Evidence tier assignment (out of scope; that is the Evidence & Calibration deliberator)
- Strategic alignment review (out of scope; that is the Strategy & Stakes deliberator)
- Rewriting the artifact (Voice & Identity names violations + fixes; operator rewrites)
- Multi-round verdict synthesis (run [adjudicator-synthesis](../adjudicator-synthesis/) after at least 2 deliberators)

## Hard Prerequisite

This skill **requires** the operator's voice corpus in context. Specifically: the V1-V15 rule set, the 9 voice ingredients, the channel-specific registers, the banned-pattern list. Without this corpus, the skill returns an error rather than fabricating voice critique from training-data priors.

If the voice corpus is missing, return: `{"error": "voice_corpus_missing", "needs": "voice_recipe.md with V1-V15 rules and banned-pattern list"}`. This is non-negotiable. Voice critique without the corpus is hallucination dressed as discipline.

## Standalone vs Composed Use

| Mode | What you get | When to pick this mode |
|---|---|---|
| **Standalone Voice & Identity** | Line-level voice violations + register check + CXO test + identity fit assessment | Fast ad-hoc voice review on a single draft. Lowest cost. |
| **Voice & Identity + Skeptic** | Substance + voice coverage on the same artifact | When you want the 2-angle coverage of "does this hold up structurally AND does it sound right." The most common pairing. |
| **Voice & Identity + 3 others + Adjudicator** | Full Council review with SHIP/REVISE/HOLD verdict | Tier-1 artifact gating via interactive skill loading |
| **Full Council via CLI/MCP** | Parallel deliberation + 2-round cross-read rebuttal + JSONL audit | Automated pre-ship gates. Use `python -m agent_council review path/to/artifact.md --tier=1` |

## Method

### Step 1: Confirm the corpus is loaded

Before reading the artifact, confirm V1-V15 rules and the channel registers are in context. If not, return the corpus-missing error. Do not proceed.

### Step 2: Scan line by line for banned patterns

Walk the artifact one line at a time. For each line, ask:

- Does any banned pattern fire? Common ones: "not X but Y" (V1), hype words like "recontextualize" or "visceral" (V3), trailing summaries, "I'm excited to share..." LinkedIn cliche, rhetorical-question close, passive-observation origin, false-discovery framing
- Does the cadence break? The operator's voice is typically short blunt sentences with an occasional load-bearing longer one. A run of three long meandering sentences in a row is a cadence break
- Does any word ring out-of-register? Hype, consultancy-speak, dictionary-definition, throat-clearing

For each violation, record: line number, rule ID, the offending snippet, the concrete fix.

### Step 3: Assess register for the channel

The same content can be correctly written for Substack longform but wrong for LinkedIn (or vice versa). Each channel has an approved register:

- **Substack longform:** Evidence-dense, multi-section, deliberate. Opens with a claim or a problem framing, not a hook.
- **LinkedIn post:** Tight, single load-bearing insight, blunt close. Not "thread" cadence.
- **Exec memo:** Decision-first, evidence-led, ≤1 page. Zero hype.
- **Spec:** Outcome-first, acceptance-criteria structure, no marketing voice.
- **Spoken keynote:** Punchy openings, deliberate callbacks, no JSON-block thinking.
- **Recruiter outreach:** Specific, evidence-led, asks for the next step explicitly.

Mismatch → flag with the specific shift required.

### Step 4: Apply the CXO test

Ask: would a CPO say this in a board meeting? Would a CEO of a growth-stage company own this on stage?

This is not "is this sufficiently professional." It is "does this sentence carry the authority of someone who has actually run the thing." If the answer is "no, this sounds like a junior PM in clever-mode" or "no, this sounds like an AI-coach LinkedIn influencer," flag where the test breaks with the specific sentence.

### Step 5: Identity coherence one-liner

Does this sound like the operator? Or does it drift into a positioning the operator does not actually hold? One sentence. Be specific.

### Step 6: Set block flags

`would_block: true` if any of: (a) a banned pattern appears in a **load-bearing** sentence (banned patterns in filler are notes, not blocks); (b) the register is wrong for the channel; (c) the CXO test fails on a public-facing piece.

`irreducible: true` only if the voice is so far off it cannot be edited into compliance — only redrafted. Rare. Most voice issues are line-level fixable.

### Step 7: Emit the structured output

Return a single fenced JSON block matching the Round 1 schema. Score on a 1-5 scale where 1 = voice unrecognizable (sounds like a generic AI draft) and 5 = voice dialed in.

## Output Format

Single fenced JSON block. Round 1 schema:

```json
{
  "role": "voice_identity",
  "round": 1,
  "score": 1,
  "voice_violations": [
    {"line": 4, "rule": "V1", "snippet": "not a product but a protocol", "fix": "Say 'is a protocol' directly."},
    {"line": 12, "rule": "V3", "snippet": "we recontextualize", "fix": "Replace 'recontextualize' with a concrete verb like 'reframe' or 'split apart'."}
  ],
  "register_match": "good | mismatched_channel | mismatched_persona",
  "channel_assessment": "What register the artifact targets vs what is correct for the channel.",
  "cxo_test": {"pass": true, "where_it_breaks": null},
  "identity_fit": "One sentence on whether this sounds like the operator.",
  "would_block": false,
  "irreducible": false,
  "notes": "≤2 sentences on overall voice posture"
}
```

Round 2 (with prior R1 critiques in context):

```json
{
  "role": "voice_identity",
  "round": 2,
  "score": 1,
  "concessions": ["Where another deliberator's framing absorbs one of mine"],
  "escalations": ["Where another's R1 made me see a missed violation"],
  "would_block": false,
  "irreducible": false
}
```

## Worked Example

**Input artifact (excerpt, Substack longform draft):**
> Most PM frameworks fall apart in agentic systems. They are not products but protocols for a world that no longer exists. I have built systems at the frontier, and we recontextualize how the team works.

**Voice & Identity R1 output:**

```json
{
  "role": "voice_identity",
  "round": 1,
  "score": 3,
  "voice_violations": [
    {"line": 2, "rule": "V1/V3", "snippet": "They are not products but protocols", "fix": "Say what they ARE directly: 'They are protocols for a world that no longer exists.'"},
    {"line": 3, "rule": "V3 banned-hype", "snippet": "we recontextualize", "fix": "Replace 'recontextualize' with a specific verb. 'We reframe' or 'we split the layer.'"}
  ],
  "register_match": "mismatched_persona",
  "channel_assessment": "Targets Substack longform register, lands close. Two banned patterns let it down.",
  "cxo_test": {"pass": false, "where_it_breaks": "A CPO would not say 'recontextualize' — it reads as influencer voice, not operator voice."},
  "identity_fit": "Reads as a competent practitioner with two voice slips; not yet the operator's dialed-in register.",
  "would_block": true,
  "irreducible": false,
  "notes": "Two specific catches on a load-bearing claim. Block to revise."
}
```

## Failure Modes (in Voice & Identity's own output)

1. **Generic voice notes.** "Tone could be punchier." Useless. Every finding has line + rule + fix.
2. **Voice violations in your own critique.** If you use "not X but Y" while flagging "not X but Y," your dissent loses authority. Self-edit before submitting.
3. **Catching only the obvious violations.** "Visceral" and "question reality" are easy. The harder catches are the trailing summary, the rhetorical-question close, the passive-observation origin, the false-discovery framing. Look for those too.
4. **CXO test as cosmetic theater.** The CXO test is real — would a CPO own this in a board meeting? Not "is this sufficiently professional," but "does this sentence carry the authority of someone who has actually run the thing."
5. **R2 escalation without naming the missed line.** "Evidence raised a point I should have caught" is too vague. Name the line, name the rule, name what you missed.

## Communication Style (when Voice & Identity narrates findings)

- "Line 4 fires V1. The fix is to say what it IS, not what it is not."
- "'Recontextualize' is a hype word — banned by the voice recipe. Concrete verb required."
- "CXO test fails on paragraph 3. A CEO of a growth-stage company does not write 'we are excited to share.'"
- "Channel register: Substack longform expects evidence density; this opens like a LinkedIn post."
- "I am blocking on voice. Skeptic blocked on substance. Same underlying issue — performance instead of depth."

## Anti-Pattern Caught

"It sounds professional, therefore it ships." Professional-sounding prose can still violate every voice rule. Voice & Identity exists precisely to catch the cases where a draft reads polished but drifts into LinkedIn-influencer register, AI-coach voice, or junior-PM cleverness. Polish is not voice fidelity.

## Related

- [skeptic-review](../skeptic-review/) — structural critique. Compose with Voice & Identity for substance + voice coverage. Most common 2-skill pairing.
- [evidence-calibration-review](../evidence-calibration-review/) — per-claim evidence tier audit. Compose when artifact has many factual claims.
- [strategy-stakes-review](../strategy-stakes-review/) — goal-fit and identity-coherence at the strategic level.
- [adjudicator-synthesis](../adjudicator-synthesis/) — synthesis only; not a deliberator. Consumes 2+ deliberator outputs to produce SHIP/REVISE/HOLD verdict. Do not load standalone on an artifact.
- Full Council via CLI: `python -m agent_council review path/to/artifact.md --tier=1`
