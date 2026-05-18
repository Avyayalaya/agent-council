---
title: Agent Council
layout: default
nav_order: 1
description: A runtime-portable 5-agent council that adjudicates text artifacts before they ship
permalink: /
---

# Agent Council
{: .fs-9 }

A runtime-portable 5-agent council that adjudicates text artifacts before they ship. Five role-conditioned LLM deliberators run in a 2-round async protocol with cross-read rebuttal. One verdict — SHIP, REVISE, or HOLD — plus a structured revision brief and a full audit transcript.
{: .fs-6 .fw-300 }

[Install](#install){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 } [View on GitHub](https://github.com/Avyayalaya/agent-council){: .btn .fs-5 .mb-4 .mb-md-0 }

---

## Why a council, not a single judge?

LLM-as-judge approaches collapse five distinct concerns into one critic:

- Is the argument adversarially sound?
- Does it match the operator's voice?
- Are the sources credible?
- Does it advance the operator's actual goals?
- Should it ship?

A unified judge averages these into one score. The Council keeps them separated. Each deliberator owns one concern, reads one context, surfaces one kind of dissent. The Adjudicator merges them — but you see *which* deliberator blocked and *why*, not just the merged number.

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
python -m agent_council review path/to/artifact.md --tier=1
```

Requires Python ≥3.11 and at least one supported LLM CLI on PATH.

### MCP server (Claude Desktop, Cursor, Cline, custom agents)

```bash
pip install mcp>=1.0
```

Add to your client's MCP config:

```json
{
  "mcpServers": {
    "agent-council": {
      "command": "python",
      "args": ["<absolute-path>/agent-council/mcp/agent_council_mcp_server.py"]
    }
  }
}
```

Tool exposed: `council_review(artifact_path, tier=1)`. Full setup in the [MCP guide](docs/mcp.html).

---

## The five roles

| Deliberator | Concern | Reads |
|---|---|---|
| **Skeptic** | Adversarial review — catches premature coherence, narrative fallacy, survivorship bias, unstated assumptions | (artifact only) |
| **Voice & Identity** | Voice DNA, banned-pattern enforcement, channel register | Operator's voice corpus + persona DNA |
| **Evidence & Calibration** | Source verification, evidence-tier classification (T1–T6), confidence levels | (artifact only) |
| **Strategy & Stakes** | Goal alignment, stake calibration, opportunity cost | Operator's goals doc + project state |
| **Adjudicator** | Merge + prior-verdict loop. Final verdict and revision brief | All four above + `council_log.jsonl` |

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

**v0.1.0** ships architecture + design only. Empirical evaluation (3-arm benchmark + arXiv paper) lands in v0.2 — see the [CHANGELOG](https://github.com/Avyayalaya/agent-council/blob/main/CHANGELOG.md).

---

## License

MIT.
