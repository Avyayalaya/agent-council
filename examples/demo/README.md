# Demo: a sample artifact + the verdict the Council produced

This directory contains a real-shaped demo of what the Council does to a tier-1 artifact. The artifact has deliberately-seeded voice violations, an under-supported claim, and a partially-addressed counter-argument — the kind of issues a producing agent typically misses on first draft.

## Files

- [`sample_linkedin_post.md`](sample_linkedin_post.md) — a 280-word LinkedIn post about a fictional framework. Four seeded issues: (1) V1 "not X but Y" construction, (2) V3 hype word "recontextualize", (3) T5 underspecified numeric claim, (4) thin counter-evidence response.
- [`sample_verdict.json`](sample_verdict.json) — the structured Council verdict for that artifact. Adjudicator returns **REVISE**. Each deliberator's specific concerns are visible.
- [`sample_revision_brief.md`](sample_revision_brief.md) — the actionable revision brief extracted from the verdict.

## How to reproduce

```bash
# From the repo root
cp council.yaml.example council.yaml
# Edit council.yaml — point context_refs at examples/ stubs, set runtime to claude_cli

python -m agent_council review examples/demo/sample_linkedin_post.md --tier=1 --config=council.yaml --json
```

Real verdicts will vary across runs (LLM-as-judge non-determinism — documented in the main README's Honest limitations section). The sample verdict in this directory is one representative run, not a fixture the test suite asserts against.

## Reading the verdict

`REVISE` calls for changes; `HOLD` flags blocking concerns or structural rework; `SHIP` clears the configured policy, not the operator's final publication decision. Scores and the model/policy merge matter as well as block counts. See the [current policy](../../README.md#how-it-works), including the non-irreducible HOLD-to-REVISE exception.

`INCOMPLETE` means insufficient valid R1 reviews or failed synthesis. The default permits three valid R1 reviews and valid-R1 fallback for failed R2; it does not require all four reviewers to finish both rounds. Missing briefs are reported explicitly. Revising the artifact and running another review is an operator action, not an automatic retry loop.

## Why this artifact

LinkedIn posts about an operator's own frameworks are a canonical Council use case — they're external-facing (tier 1), they're identity-shaping (positioning), and they typically have specific failure modes (voice violations, underspecified claims, thin evidence layers). The seeded issues here are representative of issues caught in real review sweeps on similar artifacts.
