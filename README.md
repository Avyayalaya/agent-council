# Agent Council

> *"Looks good" is not a quality gate. This is.*

A runtime-portable 5-agent council that adjudicates text artifacts before they ship. Five role-conditioned LLM deliberators run in a 2-round async protocol with cross-read rebuttal. One verdict — `SHIP`, `REVISE`, or `HOLD` — plus a structured revision brief and a full audit transcript.

No SDK. No API keys. No vendor lock-in. The Council shells out to whatever LLM CLI is configured (`claude`, `lmstudio`, `ollama`, mock). Modularity invariant is CI-tested — the council can be removed and producing agents keep working unchanged.

[Install](#install) · [How it works](#how-it-works) · [Quickstart](#quickstart) · [Customize](#customize) · [AGENTS.md](AGENTS.md) · [CHANGELOG](CHANGELOG.md)

> **v0.1.0** ships architecture + design only. Empirical evaluation (benchmark + arXiv paper) lands in v0.2 — see [Roadmap](#roadmap).

---

## Install

### Claude Code (plugin)

```bash
claude plugin marketplace add Avyayalaya/agent-council
claude plugin install agent-council@avyayalaya
```

Then in any Claude Code session: `/council-review path/to/artifact.md` or `/council-sweep`.

### Python (pip from source)

```bash
git clone https://github.com/Avyayalaya/agent-council.git
cd agent-council
pip install -e .
cp council.yaml.example council.yaml  # then edit
python -m agent_council review path/to/artifact.md --tier=1
```

Requires Python ≥3.11 and at least one supported LLM CLI on PATH.

### MCP server (Claude Desktop, Cursor, Cline, custom agents)

Coming in v0.1.1. See [issue #1](https://github.com/Avyayalaya/agent-council/issues) to track.

### Any other LLM (ChatGPT, Gemini, manual)

Read the 5 prompts at [`prompts/`](prompts/). Each is self-contained and explains what the deliberator should produce. Run them in your tool of choice, then merge the verdicts using the policy in [`src/agent_council/verdict.py`](src/agent_council/verdict.py).

---

## How it works

```
   ┌──────────┐
   │ artifact │ ───► tier-1?  No  ───► skip
   └────┬─────┘        │
        │ Yes
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
   │   Each sees the other 3 R1 verdicts; may update.       │
   │   Single-deliberator misfires get corrected; indep-    │
   │   endent first reads preserved.                        │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
   ┌────────────────────────────────────────────────────────┐
   │  ADJUDICATOR (single call)                             │
   │                                                        │
   │   Merges 4 R2 verdicts + reads prior verdicts on same  │
   │   artifact_type from council_log.jsonl (D6 loop).      │
   │                                                        │
   │   Verdict policy:                                      │
   │     3+ block on irreducible       → HOLD               │
   │     3+ block on reducible +                            │
   │       Adjudicator reasons downgrade → REVISE           │
   │     otherwise                       → SHIP             │
   │                                  + revision_brief      │
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
| **Skeptic** | Adversarial review — catches premature coherence, narrative fallacy, survivorship bias, unstated assumptions | (artifact only) |
| **Voice & Identity** | Voice DNA, banned-pattern enforcement, channel register, CXO test | Operator's voice corpus + persona DNA |
| **Evidence & Calibration** | Source verification, evidence-tier classification (T1–T6), confidence levels, base rates | (artifact only) |
| **Strategy & Stakes** | Goal alignment, stake calibration, opportunity cost vs. operator's active projects | Operator's goals doc + project state |
| **Adjudicator** | Merge + prior-verdict loop. Final verdict and revision brief | All four above + `council_log.jsonl` |

### Why a council, not a single judge?

LLM-as-judge approaches collapse five distinct concerns into one critic:

- Is the argument adversarially sound?
- Does it match the operator's voice?
- Are the sources credible?
- Does it advance the operator's actual goals?
- Should it ship?

A unified judge averages these into one score. The Council keeps them separated. Each deliberator owns one concern, reads one context, surfaces one kind of dissent. The Adjudicator merges them — but you see *which* deliberator blocked and *why*, not just the merged number.

This matters for tier-1 artifacts where the cost of shipping a flaw is high (public publish, irreversible commitment, identity-shaping document) and the cost of one more revision pass is low.

---

## Quickstart

After `pip install -e .` and copying `council.yaml.example` → `council.yaml`:

```bash
# Single artifact
python -m agent_council review path/to/artifact.md --tier=1

# Daily sweep over watch paths
python -m agent_council sweep --since=24h

# Audit recent verdicts (filter by date/verdict/artifact-type)
python -m agent_council audit --since=7d --verdict=HOLD
```

Output goes to stdout as JSON; the audit row appends to `council_log.jsonl`.

### Tier classification

The Council is designed for **tier-1 artifacts** — the ones where review cost is justified:

- **Tier 1** (gates through Council): external-facing OR irreversible OR identity-shaping OR memory writes. Examples: published writing, public READMEs, investor messages, resume revisions, additions to a learnings file, memory writes.
- **Tier 2** (skips Council): internal drafts, dashboards, infrastructure, dispatch updates.
- **Tier 3** (1-in-5 sample): daily briefings, internal analyses, planning artifacts.

Tier classification is rule-based in v0.1 — glob patterns in `council.yaml#tier_rules`. Model-based and hybrid classifiers are on the v0.3 roadmap.

---

## Built for agents

The Council was designed to be invoked from outside an agent loop, not from inside it. That's not a stylistic choice — it's a **CI-tested invariant**:

```bash
PYTHONPATH=src python -m unittest tests.test_modularity_invariant -v
```

The test scans the host operator system's `agents/*/prompt.md` files and asserts zero references to Council. If a producing agent's prompt starts to know about the gate that reviews it, the build fails.

This means:

- An orchestrator can route any artifact to Council without touching the producing agent.
- Removing the Council leaves every producing agent functional (with reduced quality on tier-1 artifacts).
- The Council ships as a **standalone runtime** — wire it into Emissary, MCP servers, slash commands, CI pipelines, or your own agent system without coupling.

[`AGENTS.md`](AGENTS.md) is the machine-readable capability manifest — agent orchestrators read this to route tasks without reading 1,300 lines of source.

---

## Customize

### Add a new runtime adapter (one file)

```python
# src/agent_council/runtimes/my_runtime.py
from .base import RuntimeAdapter

class MyRuntimeAdapter(RuntimeAdapter):
    async def invoke(self, prompt: str, *, timeout: int) -> str:
        # Shell out / HTTP / SDK call — return the model's response.
        ...
```

Register in `src/agent_council/runtimes/__init__.py`, reference by `type:` in `council.yaml`. The adapter's interface is the only contract; the orchestrator handles retries, schema validation, cross-read marshaling.

### Add a new deliberator (one prompt file)

Drop a `prompts/<name>.md` following the 5-section template:

1. **Role declaration** — who you are, what you optimize for, what you do NOT do.
2. **Methodology** — numbered steps for reading the artifact and producing the critique.
3. **Context Verification Gate** — files this deliberator must have access to.
4. **Output schema** — matching the JSON shape in [`src/agent_council/schema.py`](src/agent_council/schema.py).
5. **Communication style** — 3–5 example phrases showing the deliberator's editorial voice.

Add a block to `council.yaml#deliberators`. The orchestrator picks it up.

### Override the verdict policy

`src/agent_council/verdict.py:VerdictPolicy.apply` is the single source of truth. Subclass it and pass to the orchestrator if you need different merge semantics. Unit tests at `tests/test_verdict_merge.py` pin the default behavior — fork them for your override.

---

## Audit log

Every Council invocation appends one line to `council_log.jsonl`. Schema follows Rule 35 v2:

```json
{
  "v": 2,
  "ts": "2026-05-18T...Z",
  "artifact": "path/to/artifact.md",
  "artifact_type": "linkedin_post",
  "round1": [{"deliberator": "skeptic", "verdict": "revise", "scores": {...}, "would_block": false, "revision_brief": "..."}, ...],
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

Append-only. The Adjudicator reads prior entries on the same `artifact_type` to apply the **D6 compounding loop** — every new verdict consults the history. Two consecutive HOLDs on the same artifact_type sharpen the Adjudicator's reasoning on the third pass.

Filter with `jq` or the `audit` subcommand:

```bash
jq 'select(.adjudicator.final_verdict == "HOLD")' council_log.jsonl
python -m agent_council audit --since=7d --verdict=HOLD
```

---

## Runtimes

| Runtime | Recommended for | Notes |
|---|---|---|
| `claude_cli` | Production tier-1 gating | Requires Anthropic Claude CLI installed + authenticated. Default. |
| `lmstudio` | Local sub-sample testing | HTTP 500 on large parallel prompts at default concurrency — tune `max_concurrent` and `context_length`. |
| `ollama` | Offline / local-first | Lower-end models may not satisfy the deliberator schema; fall back to `claude_cli` for production. |
| `mock_cli` | CI / smoke tests | Canned responses for testing the orchestrator without burning tokens. |
| `gh_models` | Stub (documented fallback) | Placeholder for future GitHub Models adapter. |

Mix runtimes within a single Council run — e.g., one deliberator on `lmstudio` for style diversity, the rest on `claude_cli`. Configure per-deliberator `runtime_override:` in `council.yaml`.

---

## Roadmap

- **v0.1.0** *(this release)* — Architecture + design + 5 prompts + 4 runtimes. License: MIT.
- **v0.1.1** — MCP server wrapper (Claude Desktop, Cursor, Cline). GitHub Actions CI badge.
- **v0.2.0** — Empirical evaluation. AgentOS-Bench-style 3-arm benchmark. Recursive Council-on-Council validation study. Paper released to arXiv.
- **v0.3.0** — Adjudicator improvements + verdict-policy refinements based on 0.2 findings. Model-based and hybrid tier classifiers. Additional runtime adapters.
- **v1.0.0** — Stable verdict JSON schema, exit codes, and CLI surface. Breaking changes will bump the minor version until then.

---

## Honest limitations

- **Soft file-path coupling.** Voice & Identity and Strategy & Stakes read external context files. What they contain is the operator's responsibility.
- **Same-model self-style risk.** When all deliberators run on the same underlying model, they share that model's style preferences and may converge on its blind spots. Mitigation: run one deliberator on a different model family. Cross-model evaluation is a v0.2 work item.
- **Behavioral coupling on producing agents.** If a producing agent learns "the Council will catch X," it may loosen on X. Structural and unfixable inside the package; mitigation is operator discipline (periodic audits with Council OFF vs. ON).
- **Adjudicator non-determinism.** Same artifact can produce slightly different verdicts across runs. Documented; treated as honest LLM-as-judge variance.

---

## Tests

```bash
PYTHONPATH=src python -m unittest discover tests -v
```

105 tests. The orchestrator test uses `mock_cli`, so no real Claude tokens burn during CI.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Citation

```
Agent Council: A runtime-portable adjudicator council for tier-1 artifact gating.
v0.1.0, 2026. https://github.com/Avyayalaya/agent-council
```

A formal paper accompanies v0.2.0.
