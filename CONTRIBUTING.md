# Contributing

## New runtime adapters

One file in `src/agent_council/runtimes/` subclassing `RuntimeAdapter`. The contract is:

```python
async def invoke(self, prompt: str, *, timeout: int) -> str
```

Add an import to `src/agent_council/runtimes/__init__.py`. Add a test under `tests/test_<runtime>_adapter.py` following the `test_ollama_adapter.py` shape (monkey-patched subprocess or HTTP). The orchestrator's existing tests will exercise the contract once registered.

## New deliberators

One prompt file in `prompts/<deliberator>.md` following the 5-section template:

1. Role declaration (one paragraph)
2. Methodology (numbered steps)
3. Context Verification Gate (files this deliberator must load)
4. Output schema (matching `src/agent_council/schema.py`)
5. Communication style (3–5 example phrases)

Register in `council.yaml#deliberators`. The orchestrator picks it up automatically.

## Modifying the verdict policy

`src/agent_council/verdict.py:VerdictPolicy.apply` is the single source of truth. Changes require a unit test in `tests/test_verdict_merge.py` pinning the new semantics. Do not edit verdict logic and tests in the same commit — write the test first, see it fail, then implement.

## Bug reports

Open a GitHub issue with: artifact path, the verdict you got, the verdict you expected, and the relevant lines from `council_log.jsonl`. For runtime failures, include the schema-validation re-prompt warnings printed to stderr.

## Code style

- Python ≥3.11
- Type hints required on public APIs
- Run `python -m unittest discover tests` before opening a PR — all 105 tests must pass

## License

By contributing, you agree your work is licensed under MIT (see [LICENSE](LICENSE)).
