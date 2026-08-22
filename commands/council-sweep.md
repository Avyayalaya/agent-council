---
description: Walk the configured watch paths and run Council on every artifact modified in the last N hours (default 24h).
---

# Council Sweep

Daily-sweep mode of the Agent Council. Walks the paths declared in `council.yaml#watch.paths` and runs Council on every artifact modified in the time window.

## Pre-conditions

- The `agent-council` Python package is installed.
- A council config exists for the chosen team (see **Team selection** below), with a `watch:` block populated. If no copied config exists, the command runs from the shipped `council.<team>.yaml.example` template.

## Team selection

Like `/council-review`, this command takes a **required team name** that selects which council roster runs across the swept artifacts:

| Team name | Aliases | Config (preferred → fallback) |
|---|---|---|
| `general` | `default`, `writing` | `council.yaml` → `council.yaml.example` |
| `software` | `py`, `python`, `code` | `council.software.yaml` → `council.software.yaml.example` |
| `go` | `golang` | `council.go.yaml` → `council.go.yaml.example` |

**Resolving the config for the chosen team:** prefer the copied/customized `council.<team>.yaml`; if it does not exist, fall back to `council.<team>.yaml.example`. If neither file exists, tell the user which one to create — do not silently substitute another team.

- **No team named** → ask which team they want, listing the three names. Do not assume a default.
- **Unknown team named** → list the valid team names above; do not guess.

## Invocation

Parse a **team name** and an optional time window from the user's request. Default window is 24 hours. If the user specifies a window (e.g., "the last 3 days"), pass it via `--since`. Resolve the config per the table above, then run:

```bash
python -m agent_council sweep --since=24h --config=<resolved-config>
python -m agent_council sweep --since=72h --config=<resolved-config>
```

For example, `/council-sweep go --since=72h` resolves to `council.go.yaml` (or `council.go.yaml.example`) and runs `python -m agent_council sweep --since=72h --config=council.go.yaml`.

If the user wants a one-off scan of a specific directory not in `watch.paths`, pass `--root`:

```bash
python -m agent_council sweep --since=24h --root=./drafts/ --config=<resolved-config>
```

## Output

Print a summary table:

```
verdicts: SHIP=N · REVISE=N · HOLD=N · INCOMPLETE=N
log: council_log.jsonl (+N entries appended)
```

Then list each artifact + its verdict + one-line reason. Group by verdict (HOLD first, then REVISE, then SHIP) so the user sees blockers up front.

If the user asks "what changed since last sweep" or similar, suggest filtering by date/verdict using `jq` against `council_log.jsonl`.
