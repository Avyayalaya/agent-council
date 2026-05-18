---
description: Run the 5-agent Council on the current file or a specified path. Returns SHIP / REVISE / HOLD plus a revision brief.
---

# Council Review

Run the Agent Council against a text artifact. Five role-conditioned deliberators (Skeptic, Voice & Identity, Evidence & Calibration, Strategy & Stakes, Adjudicator) review the artifact in a 2-round async protocol with cross-read rebuttal, then synthesize a single verdict.

## Pre-conditions

Before running this command, confirm:

- The `agent-council` Python package is installed (`pip install agent-council` or `pip install -e <local-clone>`).
- A `council.yaml` exists in the working directory or a parent. If not, copy from `council.yaml.example` and edit:
  - Set `runtime.type` to your installed LLM CLI (`claude_cli`, `lmstudio`, `ollama`, `mock_cli`).
  - Point `context_refs` at your voice corpus and goals doc (templates in `examples/`).

## Invocation

If the user mentions a file path: run `python -m agent_council review <path> --tier=1 --config=council.yaml`.

If they say "this file" or "current artifact" without naming one: ask which file they mean. Do not assume.

Always run with `--tier=1` unless the user explicitly says otherwise — that's the tier this command is for.

## Output

Print the verdict (`SHIP` / `REVISE` / `HOLD`), the adjudicator's reasoning, and each deliberator's specific concerns. If `REVISE`, surface the revision brief as a numbered list the user can act on.

If the verdict is `HOLD`, do NOT propose fixes — the Council blocked for a reason; surface the blockers and let the user decide.

If the verdict is `SHIP` with concerns, list the concerns inline but make clear the artifact passed.

A full structured verdict has been appended to `council_log.jsonl`. Mention this once for the user's records.
