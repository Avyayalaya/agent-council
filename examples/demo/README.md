# Demo: a sample artifact + the verdict the Council produced

This directory contains a real-shaped demo of what the Council does to a tier-1 artifact. The artifact has deliberately-seeded voice violations, an under-supported claim, and a partially-addressed counter-argument — the kind of issues a producing agent typically misses on first draft.

## Files

- [`sample_linkedin_post.md`](sample_linkedin_post.md) — a 280-word LinkedIn post about a fictional framework. Three seeded issues: (1) V1 "not X but Y" construction, (2) V3 hype word "recontextualize", (3) T5 underspecified numeric claim, (4) thin counter-evidence response.
- [`sample_verdict.json`](sample_verdict.json) — the structured Council verdict for that artifact. Adjudicator returns **REVISE**. Each deliberator's specific concerns are visible.
- [`sample_revision_brief.md`](sample_revision_brief.md) — the actionable revision brief extracted from the verdict.

## How to reproduce

```bash
# From the repo root
cp council.yaml.example council.yaml
# Edit council.yaml — point context_refs at examples/ stubs, set runtime to claude_cli

python -m agent_council review examples/demo/sample_linkedin_post.md --tier=1
```

Real verdicts will vary across runs (LLM-as-judge non-determinism — documented in the main README's Honest limitations section). The sample verdict in this directory is one representative run, not a fixture the test suite asserts against.

## Reading the verdict

A `REVISE` verdict means:

- 1–2 deliberators flagged blocking concerns BUT the issues are reducible (line-level edits, not redrafts).
- The Adjudicator agreed the artifact can be saved with the revision brief.
- The producing agent should apply the brief and re-submit. If a second REVISE comes back, three iterations is the usual sign that the framing itself is off.

A `HOLD` verdict means:

- 3+ deliberators blocked OR any irreducible flag fired.
- The artifact needs a redraft, not an edit pass.
- Do not iterate — surface the blockers to the operator.

A `SHIP` verdict with concerns means:

- Zero blocking flags.
- Some deliberator raised non-blocking concerns worth fixing in a later pass.
- The artifact can ship; the concerns are tracked in the audit log for compounding-loop learning.

## Why this artifact

LinkedIn posts about Parth-built frameworks are a canonical Council use case — they're external-facing (tier 1), they're identity-shaping (positioning), and they typically have specific failure modes (voice violations, underspecified claims, thin evidence layers). The seeded issues here are representative of issues caught in real W5 sweeps on similar artifacts.
