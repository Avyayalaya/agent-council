# Agent Council

**A runtime-portable adjudicator council for quality-gating text artifacts.**

Five role-conditioned LLM deliberators run in a 2-round async protocol with cross-read rebuttal. They produce one verdict — `SHIP`, `REVISE`, or `HOLD` — plus a revision brief and a full audit transcript. No SDK. No API keys. Just a CLI binary you already have.

Built to sit in front of any text artifact you don't want to ship un-reviewed: published writing, public READMEs, investor messages, identity-shaping documents, memory additions to an agent system. Modularity invariant is CI-tested — the council can be removed and the producing agents keep working unchanged.

> **Status:** v0.1.0 — initial public release. Architecture + design + 5 deliberator prompts + 4 runtime adapters. Empirical evaluation forthcoming in v0.2 ([Roadmap](#roadmap)).

---

## Why a council, not a single judge?

LLM-as-judge approaches collapse five distinct concerns into one critic:
- Is the argument adversarially sound?
- Does it match the operator's voice?
- Are the sources credible?
- Does it advance the operator's actual goals?
- Should it ship?

A unified judge averages these into a single score. The council keeps them separated. Each deliberator owns one concern, reads one context, and surfaces one kind of dissent. The Adjudicator merges them — but you see *which* deliberator blocked and *why*, not just the merged number.

This matters for tier-1 artifacts where the cost of shipping a flaw is high (public publish, irreversible commitment, identity-shaping document) and the cost of not shipping a good draft is low (one more revision pass).

---

## Architecture

```
   ┌──────────┐
   │ artifact │
   └────┬─────┘
        │
        ▼
   ┌────────────────────────────────────────────────────────┐
   │  ROUND 1 — 4 deliberators run in parallel              │
   │                                                        │
   │   Skeptic        Voice &      Evidence &     Strategy  │
   │   (adversarial)  Identity     Calibration    & Stakes  │
   │                                                        │
   │   each → {verdict, scores, would_block, irreducible,   │
   │           revision_brief}                              │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
   ┌────────────────────────────────────────────────────────┐
   │  ROUND 2 — same 4 deliberators, with cross-read        │
   │                                                        │
   │   Each sees the other 3 round-1 verdicts and may       │
   │   update its position. Single-deliberator misfires     │
   │   get corrected; independent first reads preserved.    │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
   ┌────────────────────────────────────────────────────────┐
   │  ADJUDICATOR                                           │
   │                                                        │
   │   Merges 4 R2 verdicts + applies the D6 compounding    │
   │   loop (reads prior verdicts on same artifact_type     │
   │   from council_log.jsonl).                             │
   │                                                        │
   │   Verdict policy:                                      │
   │     3+ block on irreducible → HOLD                     │
   │     3+ block on reducible + Adjudicator reasons        │
   │       downgrade → REVISE (verdict-policy override)     │
   │     otherwise → SHIP (with revision_brief if any       │
   │       deliberator raised concerns)                     │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
                      SHIP / REVISE / HOLD
                      + revision_brief
                      + audit row → council_log.jsonl
```

### The five roles

| Deliberator | Concern | Reads |
|---|---|---|
| **Skeptic** | Adversarial review — pre-empts every reasonable objection. Catches premature coherence, narrative fallacy, survivorship bias. | (artifact only) |
| **Voice & Identity** | Voice DNA, banned-pattern enforcement, channel register, CXO test. | Operator's voice corpus + persona DNA |
| **Evidence & Calibration** | Source verification, evidence-tier classification (T1–T6), confidence levels, base rates. | (artifact only) |
| **Strategy & Stakes** | Goal alignment, stake calibration, opportunity cost vs. operator's active projects. | Operator's goals doc + project state |
| **Adjudicator** | Merge + prior-verdict loop. Final verdict. | All four above + `council_log.jsonl` |

### Tier classification

The Council is designed for **tier-1 artifacts** — the ones where review cost is justified:

- **Tier 1** (gates through Council): external-facing OR irreversible OR identity-shaping OR memory writes. Examples: published writing, public READMEs/AGENTS.md, investor messages, resume revisions, additions to a learnings file, memory writes.
- **Tier 2** (skips Council): internal drafts, dashboards, infrastructure, dispatch updates.
- **Tier 3** (1-in-5 sample): daily briefings, internal analyses, planning artifacts.

Tier classification is rule-based in v0.1 (glob patterns in `council.yaml#tier_rules`). Model-based and hybrid classifiers are on the v0.3 roadmap.

---

## Quickstart

### 1. Install

```bash
git clone https://github.com/Avyayalaya/agent-council.git
cd agent-council
pip install -e .
```

Requires Python ≥3.11 and at least one supported LLM CLI on `PATH` (see [Runtimes](#runtimes)).

### 2. Configure

```bash
cp council.yaml.example council.yaml
```

Edit `council.yaml`:

- Set `runtime.type` to your installed CLI (`claude_cli`, `lmstudio`, `ollama`, or `mock_cli` for smoke tests).
- Replace `./examples/voice_recipe.example.md` and `./examples/life_goals.example.md` with paths to your own voice corpus and goals doc. The example files in `examples/` show the expected structure.
- Tune `tier_rules` to match your artifact-naming conventions.

### 3. Run a review

```bash
python -m agent_council review path/to/artifact.md --tier=1 --config=council.yaml
```

Output: a JSON verdict on stdout + a v2 audit row appended to `council_log.jsonl`.

### 4. Daily sweep (optional)

```bash
python -m agent_council sweep --since=24h --config=council.yaml
```

Walks the `watch.paths` declared in `council.yaml` and runs Council on every artifact modified in the window.

---

## Runtimes

The Council shells out to whatever LLM CLI is configured. Adding a new runtime is one file in `src/agent_council/runtimes/` that subclasses `RuntimeAdapter`.

| Runtime | Recommended for | Caveats |
|---|---|---|
| `claude_cli` | Production tier-1 gating | Requires Anthropic Claude CLI installed + authenticated |
| `lmstudio` | Local sub-sample testing | HTTP 500 on large parallel prompts at default concurrency — tune `max_concurrent` and `context_length` in LM Studio settings |
| `ollama` | Offline / local-first setups | Lower-end models may not satisfy the deliberator schema; fall back to `claude_cli` for production |
| `mock_cli` | CI / smoke tests | Returns fixed canned responses for testing the orchestrator without burning tokens |
| `gh_models` | Stub (documented fallback) | Not yet implemented; placeholder for future GitHub Models adapter |

---

## Writing a new runtime adapter

```python
# src/agent_council/runtimes/my_runtime.py
from .base import RuntimeAdapter

class MyRuntimeAdapter(RuntimeAdapter):
    async def invoke(self, prompt: str, *, timeout: int) -> str:
        # Shell out to your CLI; return the model's response as a string.
        # Use asyncio.create_subprocess_exec for stdin-piped CLIs,
        # or httpx.AsyncClient for HTTP-based ones.
        ...
```

Register it in `src/agent_council/runtimes/__init__.py` and reference by `type:` in `council.yaml`.

---

## Writing a new deliberator prompt

Each deliberator prompt at `prompts/*.md` follows a 5-section template:

1. **Role declaration** — one paragraph: who you are, what you optimize for, what you do NOT do.
2. **Methodology** — how to read the artifact and produce the critique (numbered steps).
3. **Context Verification Gate** — files this deliberator must have access to before producing a verdict.
4. **Output schema** — exact JSON shape the orchestrator expects. See `src/agent_council/schema.py` for the type contract.
5. **Communication style** — 3–5 example phrases showing the deliberator's editorial voice.

Adding a new deliberator: drop a new prompt file in `prompts/`, add the deliberator block to `council.yaml#deliberators`. The orchestrator will pick it up.

---

## What lives in `council_log.jsonl`

Every Council invocation appends a single line. Schema follows Rule 35 v2:

```json
{
  "v": 2,
  "ts": "2026-05-18T...Z",
  "artifact": "path/to/artifact.md",
  "artifact_type": "linkedin_post",
  "round1": [
    {"deliberator": "skeptic", "verdict": "revise", "scores": {...}, "would_block": false, "revision_brief": "..."},
    ...
  ],
  "round2": [...],
  "adjudicator": {
    "final_verdict": "REVISE",
    "reasoning": "...",
    "revision_brief": "...",
    "applied_compounding": true,
    "prior_verdicts_consulted": 3
  }
}
```

The log is append-only. The Adjudicator reads prior entries on the same `artifact_type` to apply the D6 compounding loop — every new verdict consults the history.

---

## Roadmap

- **v0.1.0** *(this release)* — Architecture + design + 5 deliberator prompts + 4 runtime adapters. No empirical claims. License: MIT.
- **v0.2.0** — Empirical evaluation. AgentOS-Bench-style 3-arm benchmark (baseline / unified-judge / Council). Recursive Council-on-Council validation study. Paper released to arXiv.
- **v0.3.0** — Adjudicator improvements + verdict-policy refinements based on 0.2 findings. Model-based and hybrid tier classifiers. Additional runtime adapters.
- **v1.0.0** — Stable verdict JSON schema, exit codes, and CLI surface. Breaking changes will bump the minor version until 1.0.

The verdict JSON schema, exit codes, and CLI subcommand names are the public surface; everything else is internal and may change between minor versions.

---

## Honest limitations

- **Soft file-path coupling.** The Voice & Identity and Strategy & Stakes deliberators read external context files (your voice corpus, your goals doc). Council reads them as arbitrary text via the filesystem; what they contain is the operator's responsibility.
- **Same-model self-style risk.** When all deliberators run on the same underlying model (e.g., all `claude_cli`), they share that model's style preferences and may converge on its blind spots. Mitigation: use the `lmstudio` or `ollama` runtime for one deliberator to introduce style diversity. Cross-model evaluation is a v0.2 work item.
- **Behavioral coupling on producing agents.** If a producing agent learns "the Council will catch X," it may loosen on X. This is structural and unfixable inside the package; the mitigation is operator discipline — periodic audits of producing agents' outputs with Council OFF vs. ON.
- **Adjudicator non-determinism.** Same artifact can produce slightly different verdicts across runs. Documented; treated as honest LLM-as-judge variance. The verdict-policy override only fires when the Adjudicator explicitly argues a downgrade.

---

## Tests

```bash
PYTHONPATH=src python -m unittest discover tests -v
```

The orchestrator test uses `mock_cli`, so no real Claude tokens burn during CI runs.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Citation

If you reference the Council in research or writing, please cite:

```
Agent Council: A runtime-portable adjudicator for tier-1 artifact gating.
v0.1.0, 2026. https://github.com/Avyayalaya/agent-council
```

A formal paper accompanies v0.2.0.

---

*Built for operators who want structured dissent before they ship — not just "looks good."*
