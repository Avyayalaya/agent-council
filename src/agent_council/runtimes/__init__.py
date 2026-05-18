"""Runtime adapters for invoking LLM CLIs from the Council orchestrator.

Every adapter implements `RuntimeAdapter` and exposes a stable interface:
async invoke(prompt, context, model) -> str; health_check() -> bool; adapter_name() -> str.

Adding a new runtime = one new file in this directory + a `type:` registry entry.
"""

from agent_council.runtimes.base import RuntimeAdapter
from agent_council.runtimes.claude_cli import ClaudeCLIAdapter
from agent_council.runtimes.gh_models import GhModelsAdapter
from agent_council.runtimes.lmstudio import LMStudioAdapter
from agent_council.runtimes.mock_cli import MockCLIAdapter
from agent_council.runtimes.ollama import OllamaAdapter


def build_adapter(runtime_config: dict) -> RuntimeAdapter:
    """Instantiate the adapter declared in ``council.yaml#runtime``.

    Args:
        runtime_config: parsed runtime block from council.yaml.

    Returns:
        A concrete RuntimeAdapter instance ready for ``invoke()``.

    Raises:
        ValueError: if the runtime type is unknown.
    """
    rt = (runtime_config.get("type") or "").lower()
    if rt == "claude_cli":
        return ClaudeCLIAdapter(runtime_config)
    if rt == "mock_cli":
        return MockCLIAdapter(runtime_config)
    if rt == "ollama":
        return OllamaAdapter(runtime_config)
    if rt == "gh_models":
        return GhModelsAdapter(runtime_config)
    if rt == "lmstudio":
        return LMStudioAdapter(runtime_config)
    raise ValueError(
        f"Unknown runtime type: {rt!r}. "
        f"Known: claude_cli, mock_cli, ollama, gh_models, lmstudio. "
        f"Add a new adapter to src/agent_council/runtimes/ and register it here."
    )


__all__ = [
    "RuntimeAdapter",
    "ClaudeCLIAdapter",
    "GhModelsAdapter",
    "LMStudioAdapter",
    "MockCLIAdapter",
    "OllamaAdapter",
    "build_adapter",
]
