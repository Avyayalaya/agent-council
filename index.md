---
title: Agent Council
layout: default
nav_order: 1
description: A runtime-portable 5-agent council that adjudicates text artifacts before they ship
permalink: /
---

# Agent Council
{: .fs-9 }

A runtime-portable gate for authored, AI-generated and co-created text. Four reviewers take independent first perspectives, share their full findings for one second review, and pass both rounds to a separate Adjudicator. Code enforces SHIP, REVISE, HOLD or INCOMPLETE; the decision includes reasons, required changes and visible disagreement.
{: .fs-6 .fw-300 }

[Install](#install){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 } [View on GitHub](https://github.com/Avyayalaya/agent-council){: .btn .fs-5 .mb-4 .mb-md-0 }

---

## Why a council, not a single judge?

Review requires distinct questions:

- Is the argument adversarially sound?
- Does it match the operator's voice?
- Are the sources credible?
- Does it advance the operator's actual goals?
- Should it ship?

A single judge can cover multiple criteria. Council makes the responsibilities explicit and preserves who raised an issue and what changed after cross-reading. This can expose new questions and angles, but does not prove better judgments or require reviewers to agree. Read the [implementation details](docs/architecture.html) and the [author's review workflow](https://github.com/Avyayalaya/agent-council#my-review-workflow); the diagram is not an exact runtime state machine.

---

## Install

### Claude Code (plugin)

```bash
claude plugin marketplace add Avyayalaya/agent-council
claude plugin install agent-council@avyayalaya
```

Then in any Claude Code session: `/council-review path/to/artifact.md`.

### Python (pip from source)

```bash
git clone https://github.com/Avyayalaya/agent-council.git
cd agent-council
pip install -e .
cp council.yaml.example council.yaml  # then edit
python -m agent_council review path/to/artifact.md --tier=1 --config=council.yaml
```

Requires Python ≥3.11 and a configured runtime. The offline mock needs no model; other adapters require their configured CLI or server.

### MCP server (Claude Desktop, Cursor, Cline, custom agents)

```bash
pip install "mcp>=1.0"
```

Add to your client's MCP config:

```json
{
  "mcpServers": {
    "agent-council": {
      "command": "python",
      "args": ["<absolute-path>/agent-council/mcp/agent_council_mcp_server.py"],
      "env": {
        "COUNCIL_CONFIG": "<absolute-path>/agent-council/council.yaml"
      }
    }
  }
}
```

Tool exposed: `council_review(artifact_path, tier=1)`. Full setup in the [MCP guide](docs/mcp.html).

---

## The five roles

| Role | Concern | Reads |
|---|---|---|
| **Skeptic** | Adversarial review — catches premature coherence, narrative fallacy, survivorship bias, unstated assumptions | (artifact only) |
| **Voice & Identity** | Voice DNA, banned-pattern enforcement, channel register | Operator's voice corpus + persona DNA |
| **Evidence & Calibration** | Review supplied support, evidence tiers (T1–T6), confidence and missing evidence; no built-in source retrieval | Artifact + optional supplied source text |
| **Strategy & Stakes** | Goal alignment, stake calibration, opportunity cost | Operator's goals doc + project state |
| **Adjudicator** | Separate synthesis, recommendation and revision brief; code enforces policy | Both rounds + prior verdict summaries |

---

## Modularity invariant

Emitting agents have **zero hard dependency on Council**. This is CI-tested:

- No emitting-agent prompt references Council, `council_review()`, or `council.yaml`.
- Council is invoked from outside the agent loop.
- Removing the Council leaves every producing agent functional.

This means the Council ships as a standalone runtime — wire it into Emissary, MCP servers, slash commands, CI pipelines, or your own agent system without coupling.

---

## See it work

[Read the demo](https://github.com/Avyayalaya/agent-council/tree/main/examples/demo): a fictional LinkedIn post + the structured verdict the Council produced + the extracted revision brief. Calibrates expectations before you run your first real review.

---

## Status

The Python package includes a working review protocol and mock/scripted tests. Its default remains three schema-valid R1 reviews, with valid-R1 fallback when R2 fails. Failed synthesis yields INCOMPLETE. It does not guarantee every reviewer completed both rounds.

Comparative quality improvement has not been demonstrated in published repository results. Benchmark scaffolding exists; empirical evaluation and a companion paper remain planned in the [CHANGELOG](https://github.com/Avyayalaya/agent-council/blob/main/CHANGELOG.md).

---

## License

MIT.
