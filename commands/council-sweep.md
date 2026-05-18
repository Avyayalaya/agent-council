---
description: Walk the configured watch paths and run Council on every artifact modified in the last N hours (default 24h).
---

# Council Sweep

Daily-sweep mode of the Agent Council. Walks the paths declared in `council.yaml#watch.paths` and runs Council on every artifact modified in the time window.

## Pre-conditions

- The `agent-council` Python package is installed.
- A `council.yaml` exists with a `watch:` block populated.

## Invocation

Default window is 24 hours. If the user specifies a window (e.g., "the last 3 days"), pass it via `--since`:

```bash
python -m agent_council sweep --since=24h --config=council.yaml
python -m agent_council sweep --since=72h --config=council.yaml
```

If the user wants a one-off scan of a specific directory not in `watch.paths`, pass `--root`:

```bash
python -m agent_council sweep --since=24h --root=./drafts/ --config=council.yaml
```

## Output

Print a summary table:

```
verdicts: SHIP=N · REVISE=N · HOLD=N · INCOMPLETE=N
log: council_log.jsonl (+N entries appended)
```

Then list each artifact + its verdict + one-line reason. Group by verdict (HOLD first, then REVISE, then SHIP) so the user sees blockers up front.

If the user asks "what changed since last sweep" or similar, suggest filtering by date/verdict using `jq` against `council_log.jsonl`.
