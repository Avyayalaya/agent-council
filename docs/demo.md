---
title: Demo
layout: default
nav_order: 4
---

# Demo

A fictional LinkedIn post + the verdict the Council produced.
{: .fs-6 .fw-300 }

The [`examples/demo/`](https://github.com/Avyayalaya/agent-council/tree/main/examples/demo) directory ships a real-shaped demo of what the Council does. Read this to calibrate expectations before your first review.

---

## What's in the demo

| File | Purpose |
|---|---|
| [`sample_linkedin_post.md`](https://github.com/Avyayalaya/agent-council/blob/main/examples/demo/sample_linkedin_post.md) | 280-word LinkedIn post about a fictional framework (Lattice). 4 seeded issues. |
| [`sample_verdict.json`](https://github.com/Avyayalaya/agent-council/blob/main/examples/demo/sample_verdict.json) | Full structured verdict the Council produced. REVISE. |
| [`sample_revision_brief.md`](https://github.com/Avyayalaya/agent-council/blob/main/examples/demo/sample_revision_brief.md) | Human-readable revision brief extracted from the verdict. |

---

## The seeded issues

1. **V1 voice violation** — "Not a product but a protocol" (split-form negation-pivot)
2. **V3 voice violation** — "recontextualizes how a PM team works" (hype word)
3. **T5 calibration** — "cycle time dropped by half" (unsourced operator claim)
4. **Thin counter-evidence** — self-serve counter named but response is rhetorical, not evidential

The Council catches all four. Skeptic + Voice + Evidence each block; Strategy passes outright. The Adjudicator merges → REVISE with a 6-step revision brief.

---

## Reading the verdict

A `REVISE` verdict means:

- 1–2 (or 3+) deliberators flagged blocking concerns BUT the issues are reducible (line-level edits, not redrafts).
- The Adjudicator agreed the artifact can be saved with the revision brief.
- The producing agent should apply the brief and re-submit.

A `HOLD` verdict means:

- 3+ deliberators blocked OR any irreducible flag fired.
- The artifact needs a redraft, not an edit pass.
- Do not iterate — surface the blockers to the operator.

A `SHIP` verdict with concerns means:

- Zero blocking flags.
- Some deliberator raised non-blocking concerns worth fixing in a later pass.
- The artifact can ship; the concerns are tracked in the audit log for compounding-loop learning.

---

## Reproduce

```bash
# From the repo root
cp council.yaml.example council.yaml
# Edit council.yaml — point context_refs at examples/ stubs, set runtime to claude_cli

python -m agent_council review examples/demo/sample_linkedin_post.md --tier=1
```

Real verdicts will vary across runs (LLM-as-judge non-determinism — documented in [Honest limitations](architecture.html)). The sample verdict in the demo is one representative run, not a fixture the test suite asserts against.
