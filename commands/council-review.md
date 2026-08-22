---
description: Run the 5-agent Council on the current file or a specified path. Returns SHIP / REVISE / HOLD plus a revision brief.
---

# Council Review

Run the Agent Council against a text artifact. Five role-conditioned deliberators (Skeptic, Voice & Identity, Evidence & Calibration, Strategy & Stakes, Adjudicator) review the artifact in a 2-round async protocol with cross-read rebuttal, then synthesize a single verdict.

## Pre-conditions

Before running this command, confirm:

- The `agent-council` Python package is installed (`pip install agent-council` or `pip install -e <local-clone>`).
- A council config exists for the chosen team (see **Team selection** below). If none exists, the command runs from the shipped `*.yaml.example` template, so no setup is required to get started. To customize, copy the example to the real filename and edit:
  - Set `runtime.type` to your installed LLM CLI (`copilot_cli`, `claude_cli`, `lmstudio`, `ollama`, `mock_cli`).
  - Point `context_refs` at your corpora (templates in `examples/`).

## Team selection

This command takes a **required team name** that selects which council roster runs. The Skeptic, Evidence, and Adjudicator seats are shared by every team; each team re-casts the other two seats:

| Team name | Aliases | Config (preferred → fallback) |
|---|---|---|
| `general` | `default`, `writing` | `council.yaml` → `council.yaml.example` |
| `software` | `py`, `python`, `code` | `council.software.yaml` → `council.software.yaml.example` |
| `go` | `golang` | `council.go.yaml` → `council.go.yaml.example` |

**Resolving the config for the chosen team:** prefer the copied/customized `council.<team>.yaml`; if it does not exist, fall back to `council.<team>.yaml.example`. For `general`, that is `council.yaml` → `council.yaml.example`. If neither file exists, tell the user which one to create — do not silently substitute another team.

## Invocation

Parse two things from the user's request: a **file path** and a **team name**.

- **No team named** → ask which team they want, listing the three names (`general`, `software`, `go`). Do not assume a default.
- **Unknown team named** (e.g. `rust`) → list the valid team names above; do not guess.
- **`this file` / `current artifact` without a path** → ask which file they mean. Do not assume.

Once you have both, resolve the config per the table above and run:

```bash
python -m agent_council review <path> --tier=1 --config=<resolved-config>
```

For example, `/council-review pkg/foo.go go` resolves to `council.go.yaml` (or `council.go.yaml.example`) and runs `python -m agent_council review pkg/foo.go --tier=1 --config=council.go.yaml`.

Always run with `--tier=1` unless the user explicitly says otherwise — that's the tier this command is for.

## Output

Print the verdict (`SHIP` / `REVISE` / `HOLD`), the adjudicator's reasoning, and each deliberator's specific concerns. If `REVISE`, surface the revision brief as a numbered list the user can act on.

If the verdict is `HOLD`, do NOT propose fixes — the Council blocked for a reason; surface the blockers and let the user decide.

If the verdict is `SHIP` with concerns, list the concerns inline but make clear the artifact passed.

A full structured verdict has been appended to `council_log.jsonl`. Mention this once for the user's records.
