# Decision Memo — `copilot_cli` runtime adapter

**Status:** Implemented · **Date:** 2026-05-11 · **Scope:** additive (new adapter only)

## Decision

Add a new `copilot_cli` runtime adapter that drives the GitHub **`copilot`** CLI
in non-interactive mode, so the Council can run on GitHub Copilot as its LLM
backend alongside `claude_cli`. Do **not** build on `gh_models` (a documented
stub whose `invoke()` raises `NotImplementedError`; `gh models` is not installed
in the target environment).

## Why `copilot`, not `gh models`

| Option | Status | Verdict |
|--------|--------|---------|
| `gh_models` adapter | Stub — `invoke()` raises; `gh models` extension absent | Dead end |
| `copilot -p` CLI | On PATH; supports non-interactive scripting | **Chosen** |

## Investigation (verified, not assumed)

`copilot --help` confirmed the non-interactive surface:

- `-p, --prompt <text>` — run a prompt non-interactively and exit.
- `-s, --silent` — "Output only the agent response (no stats), useful for scripting with -p".
- `--model <model>` — select model (`auto` lets Copilot pick).
- `--allow-all-tools` — documented requirement for non-interactive mode (prevents TTY permission blocking).
- `--no-custom-instructions`, `--disable-builtin-mcps`, `--no-color`, `--log-level`, `--no-auto-update`.

**Live probe (key evidence):**

```
copilot -p "Reply with exactly the word: PONG" -s --no-color \
  --no-custom-instructions --disable-builtin-mcps --log-level none \
  --no-auto-update --deny-tool=shell --deny-tool=write
```

→ exit `0`, stdout = `PONG\n`, stderr empty, **no permission prompt**. Proves:
`-s` output is clean (no banner/stats), the prompt is accepted as an **argument**
(not stdin), and a pure-text prompt does not trigger a tool-permission prompt
even without `--allow-all-tools`.

## Design consequences

1. **Args, not stdin.** Unlike `claude_cli`/`ollama` (which pipe the prompt over
   stdin), the composed prompt is the **final arg after `-p`**. `stdin` is closed
   (`DEVNULL`) so a call can never block on a TTY. `create_subprocess_exec` (no
   shell) makes newlines/quotes in the prompt arg safe.
2. **`--no-custom-instructions` is mandatory in practice.** This repo's
   `AGENTS.md` *describes the Council itself*; without this flag it would be
   injected into every deliberator call and pollute critiques.
3. **No new dependencies.** Adapter uses only stdlib (`asyncio`, `shutil`,
   `sys`, `subprocess`) + the `RuntimeAdapter` base → the CI modularity invariant
   stays green.

## Permission strategy

Default example-config `flags` include `--allow-all-tools` (Copilot's documented
non-interactive requirement, guarantees no TTY block). Deliberator prompts are
pure-text critique, so no tools execute in practice. For a strictly read-only
gate, swap for `--deny-tool=shell --deny-tool=write`.

## Risks

1. **Output parsing noise** — *Low.* `-s` returns the bare answer; the
   orchestrator's fence-tolerant schema parser absorbs any JSON wrapped in prose.
2. **Permission / TTY blocking** — *Low.* `--allow-all-tools` + `stdin=DEVNULL`.
3. **Latency / rate-limits / credits** — *Medium, operational.* Each `copilot -p`
   is a full agent turn; 9 calls per Council run. Mitigate with
   `timeout_seconds: 600`; watch Copilot auth / AI-credit / rate-limit exposure.

## Files

- `src/agent_council/runtimes/copilot_cli.py` — new `CopilotCLIAdapter`.
- `src/agent_council/runtimes/__init__.py` — registry wiring.
- `tests/test_copilot_adapter.py` — 10 unit tests (mocked subprocess).
- `council.yaml.example`, `README.md`, `AGENTS.md` — runtime enumeration + config block.
