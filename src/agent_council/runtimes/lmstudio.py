"""LMStudioAdapter — drives the LM Studio HTTP server (OpenAI-compatible).

LM Studio is the third runtime adapter (D7, P2 W4). It targets LM Studio's
**OpenAI-compatible Local Server** which by default listens on
``http://localhost:1234/v1``. The same surface is exposed by any
OpenAI-compatible endpoint, so this adapter doubles as the canonical
**OpenAI-compatible template** for the Council. Adopters who later want to
wire vLLM, llama.cpp's OpenAI server, LocalAI, or a future Cohere-compatible
endpoint can copy this file, change ``base_url``, and ship.

Why a 3rd adapter beyond ``ollama``:

  1. **Local-machine reality.** LM Studio is what's actually installed on the
     operator's machine as of W4 (P2 W4 D7) — ``ollama`` was the planned
     second adapter, but not present. LM Studio fills the gap with a clean
     HTTP surface and zero CLI shell-out.
  2. **HTTP, not subprocess.** Unlike ``claude_cli`` / ``ollama``, there is
     no binary to invoke. The adapter speaks HTTP to a long-running server,
     which means no per-call process spawn (faster), no stdin escape concerns,
     and no Windows ProactorEventLoop dance for asyncio subprocess.
  3. **OpenAI-compatible.** ``POST {base_url}/chat/completions`` with a JSON
     body of ``{"model": ..., "messages": [...]}`` — the same shape every
     OpenAI-compatible runtime accepts. This adapter is the template for any
     such future runtime; document the swap inline.

**Invocation surface (W4):**

  - HTTP POST to ``{base_url}/chat/completions``.
  - JSON body: ``{"model": ..., "messages": [...], "stream": false}``.
  - Each ``context`` blob is a ``role: system`` message; the user prompt is a
    final ``role: user`` message.
  - Streaming mode is NOT supported in v1 — single-shot completions only.
    A v2 follow-up could add server-sent-events handling via
    ``urllib.request.urlopen`` line iteration; for now ``stream=false`` is
    hardcoded. The Council orchestrator processes complete responses anyway,
    so streaming is a performance win, not a correctness one. (v2 TODO.)

**Config (read from council.yaml#runtime):**

  - ``base_url`` (default ``http://localhost:1234/v1``)
  - ``model`` (e.g. ``qwen2.5-7b-instruct`` — operator picks based on what
    they've loaded into LM Studio Server)
  - ``api_key`` (optional; defaults to empty. LM Studio Server doesn't
    require auth in default config. Sent as
    ``Authorization: Bearer <api_key>`` if non-empty — same shape as OpenAI,
    so this field also covers future OpenAI-compatible endpoints that do
    require auth.)
  - ``timeout_seconds`` (default 600 — sized for ~1500-word artifacts on
    7B-class local models, matching ``claude_cli`` default.)

**stdlib only.** Uses ``urllib.request`` + ``json`` + ``asyncio`` — no
``requests``, no ``httpx``, no openai SDK. The modularity invariant (no new
external deps in ``src/agent_council/``) stays green.

See ``docs/adapters.md`` for the W4 choice rationale and adopter guide.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Iterable

from agent_council.runtimes.base import RuntimeAdapter


_DEFAULT_BASE_URL = "http://localhost:1234/v1"
_HEALTH_TIMEOUT = 15.0


class LMStudioAdapter(RuntimeAdapter):
    """Adapter that drives LM Studio's OpenAI-compatible HTTP server.

    Also serves as the **template adapter for any OpenAI-compatible runtime**
    (vLLM, llama.cpp server, LocalAI, future Cohere endpoints, etc.). Swap
    ``base_url`` and ``model`` in the config — no code changes needed.

    Config (from council.yaml#runtime):
        type: lmstudio
        base_url: http://localhost:1234/v1
        model: qwen2.5-7b-instruct
        api_key: ""                   # optional; LM Studio doesn't require auth
        timeout_seconds: 600

    Note: ``binary`` / ``flags`` / ``invocation_pattern`` from the base class
    are ignored for this adapter — the runtime is HTTP, not subprocess.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # HTTP-specific config; falls back to LM Studio defaults.
        self.base_url: str = (config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        self.api_key: str = config.get("api_key") or ""
        # The base class defaults timeout to 180; LM Studio with a 7B model on
        # CPU can take longer. Allow caller override but bump the default.
        if "timeout_seconds" not in config:
            self.timeout_seconds = 600.0

    def adapter_name(self) -> str:
        return "lmstudio"

    # ------------------------------------------------------------------
    # health_check
    # ------------------------------------------------------------------
    def health_check(self) -> bool:
        """GET ``{base_url}/models`` and assert the configured model is listed.

        Returns True iff:
          (a) the server responds with HTTP 200, AND
          (b) the configured ``self.default_model`` appears in the response
              (matched against each entry's ``id`` field).

        If ``self.default_model`` is empty (operator deferred picking), we
        relax to "any model loaded" (the response contains at least one
        entry). That lets ``health`` pass on a fresh-boot server before the
        operator has finalized their model choice.
        """
        url = f"{self.base_url}/models"
        req = urllib.request.Request(url, method="GET")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
                if resp.status != 200:
                    return False
                body = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
            return False
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return False

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return False

        if not self.default_model:
            # No model declared — pass as long as something is loaded.
            return len(data) > 0

        for entry in data:
            if isinstance(entry, dict) and entry.get("id") == self.default_model:
                return True
        return False

    # ------------------------------------------------------------------
    # invoke
    # ------------------------------------------------------------------
    async def invoke(
        self,
        prompt: str,
        context: Iterable[str],
        model: str | None = None,
    ) -> str:
        """POST a chat-completions request and return the assistant's content.

        Wraps the sync ``urllib`` call in ``asyncio.to_thread`` + ``wait_for``
        so the timeout contract from the base class still applies cleanly.

        Args:
            prompt: deliberator (or adjudicator) prompt text — sent as the
                final ``role: user`` message.
            context: ordered iterable of context blobs (artifact, prior
                critiques, role-specific context) — each becomes its own
                ``role: system`` message in order. We use system messages
                (not concatenated into the user message) because that's
                what OpenAI-compatible servers expect: system frames the
                model, user asks the question.
            model: optional override for ``self.default_model``.

        Returns:
            The assistant's response content as a plain UTF-8 string.

        Raises:
            asyncio.TimeoutError: if the call exceeds ``self.timeout_seconds``.
            RuntimeError: on non-2xx HTTP status, invalid JSON, or a missing
                ``choices[0].message.content`` field.
        """
        chosen_model = model or self.default_model or ""

        messages: list[dict[str, str]] = []
        for blob in context:
            if blob:
                messages.append({"role": "system", "content": blob})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, object] = {
            "model": chosen_model,
            "messages": messages,
            "stream": False,
        }

        payload = json.dumps(body).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        # Run the sync urllib call in a thread, gated by the configured
        # timeout. ``asyncio.wait_for`` is the authoritative timeout — it
        # raises ``asyncio.TimeoutError`` even if the worker thread is stuck
        # (the thread is leaked until urllib's own socket timeout fires,
        # which is why we pass it as well). This double-gate satisfies the
        # RuntimeAdapter contract: caller sees TimeoutError within the budget.
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_do_post, req, self.timeout_seconds),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"lmstudio: response was not valid JSON: {e}: {raw[:200]!r}"
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(
                f"lmstudio: response missing choices[0].message.content: "
                f"{raw[:500]!r}"
            )
        if not isinstance(content, str):
            raise RuntimeError(
                f"lmstudio: choices[0].message.content is not a string: "
                f"{type(content).__name__}"
            )
        return content


# ---------------------------------------------------------------------------
# Module-level helper — kept at module scope so tests can patch
# ``urllib.request.urlopen`` and intercept the call in one place.
# ---------------------------------------------------------------------------

def _do_post(req: urllib.request.Request, timeout: float) -> str:
    """Synchronously POST ``req`` and return the body decoded as UTF-8.

    Raises ``RuntimeError`` on HTTP 4xx/5xx (with the status + body excerpt
    in the message) or any other ``URLError``/``OSError`` from urllib.
    """
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body_b = resp.read()
    except urllib.error.HTTPError as e:
        # Surface 4xx/5xx with the body so the operator sees model_not_found
        # or auth errors instead of a bare "HTTP 404".
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise RuntimeError(
            f"lmstudio: HTTP {e.code} from {req.full_url}: "
            f"{err_body[:500] or e.reason}"
        )
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(
            f"lmstudio: request to {req.full_url} failed: {e}"
        )

    body = body_b.decode("utf-8", errors="replace")
    if status < 200 or status >= 300:
        raise RuntimeError(
            f"lmstudio: HTTP {status} from {req.full_url}: {body[:500]}"
        )
    return body
