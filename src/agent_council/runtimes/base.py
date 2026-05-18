"""RuntimeAdapter — the abstract interface every runtime must implement.

The Council orchestrator depends ONLY on this interface. Concrete adapters
(ClaudeCLIAdapter, MockCLIAdapter, future CopilotCLIAdapter / OllamaAdapter)
swap behind the same surface, so changing runtimes is a config edit, not a
code edit.

Contract (every adapter must honor):
    - ``invoke`` returns model output as a str, completes within
      ``self.timeout_seconds`` or raises asyncio.TimeoutError.
    - ``health_check`` is sync and fast (<30s); returns True if the runtime
      is usable right now.
    - ``adapter_name`` returns a stable identifier used in logs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable


class RuntimeAdapter(ABC):
    """Abstract base for any LLM CLI runtime the Council can drive."""

    def __init__(self, config: dict) -> None:
        """Initialize from a parsed council.yaml#runtime block.

        Args:
            config: runtime block; expected keys include ``binary``,
                ``model``, ``flags``, ``invocation_pattern``, ``timeout_seconds``.
        """
        self.config = config
        self.binary: str = config.get("binary", "")
        self.default_model: str = config.get("model", "")
        self.flags: list[str] = list(config.get("flags") or [])
        self.invocation_pattern: str = config.get("invocation_pattern", "stdin")
        self.timeout_seconds: float = float(config.get("timeout_seconds", 180))

    @abstractmethod
    async def invoke(
        self,
        prompt: str,
        context: Iterable[str],
        model: str | None = None,
    ) -> str:
        """Send a prompt + context to the runtime and return its raw output.

        Args:
            prompt: the deliberator (or adjudicator) prompt text.
            context: ordered iterable of context blobs (artifact, prior critiques,
                role-specific context files). Joined with separator before send.
            model: optional override for ``self.default_model``.

        Returns:
            Raw model output as a single string.

        Raises:
            asyncio.TimeoutError: if invocation exceeds ``self.timeout_seconds``.
            RuntimeError: if the underlying runtime returns a non-zero exit code
                or fails in a way the adapter cannot recover from.
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        """Verify the runtime is usable. Should be cheap (<30s) and non-destructive.

        Returns:
            True if the runtime binary resolves, the model is configured,
            and a trivial call would likely succeed. False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def adapter_name(self) -> str:
        """Stable identifier used for logging. e.g. ``"claude_cli"``, ``"mock_cli"``."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared helpers — concrete adapters can use these or override.
    # ------------------------------------------------------------------
    @staticmethod
    def join_context(context: Iterable[str]) -> str:
        """Default context join: blobs separated by ``\\n\\n---\\n\\n``."""
        parts = [p for p in context if p]
        return "\n\n---\n\n".join(parts)

    def build_full_prompt(self, prompt: str, context: Iterable[str]) -> str:
        """Compose the final string sent to the runtime.

        Context comes first (so the model anchors on it), then a separator,
        then the deliberator prompt. Override for runtimes that prefer the
        opposite order.
        """
        ctx = self.join_context(context)
        if not ctx:
            return prompt
        return f"{ctx}\n\n---\n\n{prompt}"
