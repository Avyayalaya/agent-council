"""Unit tests for LMStudioAdapter — D7, third runtime adapter.

We don't hit a real LM Studio server in tests. Instead we patch
``urllib.request.urlopen`` (via ``agent_council.runtimes.lmstudio`` module
namespace) with a context manager that returns canned JSON, asserting:

  - happy path: ``invoke`` returns ``choices[0].message.content`` as a str
  - context blobs become system messages, prompt becomes user message
  - HTTP 4xx surfaces as RuntimeError with the body excerpt
  - timeout passes through as asyncio.TimeoutError
  - health_check returns True when configured model is in /models response
  - health_check returns False on connection error, on missing model,
    and on non-200 status
  - adapter_name is "lmstudio"
  - build_adapter resolves type=lmstudio
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.runtimes import build_adapter  # noqa: E402
from agent_council.runtimes.lmstudio import LMStudioAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Fake urllib response — minimal context-manager that mimics http.client's
# Response just enough for the adapter to read it.
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal stand-in for ``http.client.HTTPResponse`` as a CM."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status
        self._read = False

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:  # noqa: D401
        return None

    def read(self) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body


def _make_chat_response(content: str) -> bytes:
    """Build a JSON body shaped like OpenAI's chat completions response."""
    return json.dumps({
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "qwen2.5-7b-instruct",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }).encode("utf-8")


def _make_models_response(model_ids: list[str]) -> bytes:
    """Build a JSON body shaped like OpenAI's /v1/models response."""
    return json.dumps({
        "object": "list",
        "data": [{"id": mid, "object": "model"} for mid in model_ids],
    }).encode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class LMStudioAdapterTest(unittest.TestCase):
    """Contract tests for the lmstudio runtime adapter."""

    def _adapter(self, **overrides) -> LMStudioAdapter:
        cfg = {
            "type": "lmstudio",
            "base_url": "http://localhost:1234/v1",
            "model": "qwen2.5-7b-instruct",
            "api_key": "",
            "timeout_seconds": 30,
        }
        cfg.update(overrides)
        return LMStudioAdapter(cfg)

    # ------------------------------------------------------------------
    # Identity / wiring
    # ------------------------------------------------------------------

    def test_adapter_name(self) -> None:
        self.assertEqual("lmstudio", self._adapter().adapter_name())

    def test_registry_resolves_lmstudio(self) -> None:
        adapter = build_adapter({
            "type": "lmstudio",
            "base_url": "http://localhost:1234/v1",
            "model": "qwen2.5-7b-instruct",
        })
        self.assertIsInstance(adapter, LMStudioAdapter)

    def test_base_url_default(self) -> None:
        adapter = LMStudioAdapter({"type": "lmstudio", "model": "x"})
        self.assertEqual("http://localhost:1234/v1", adapter.base_url)

    def test_base_url_trailing_slash_stripped(self) -> None:
        adapter = LMStudioAdapter({
            "type": "lmstudio",
            "base_url": "http://example.com:8000/v1/",
            "model": "x",
        })
        self.assertEqual("http://example.com:8000/v1", adapter.base_url)

    # ------------------------------------------------------------------
    # invoke — happy path
    # ------------------------------------------------------------------

    def test_invoke_returns_choice_content(self) -> None:
        """Happy path: response content surfaces as the return value."""
        adapter = self._adapter()
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["body"] = req.data
            captured["headers"] = dict(req.header_items())
            return _FakeResponse(_make_chat_response("hello from LM Studio"))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            out = asyncio.run(adapter.invoke(
                "What is the capital of France?",
                ["Context: you are a geography tutor."],
            ))

        self.assertEqual("hello from LM Studio", out)
        self.assertEqual("http://localhost:1234/v1/chat/completions", captured["url"])
        self.assertEqual("POST", captured["method"])

        # Verify the JSON body shape: each context blob = system message;
        # prompt = user message; model carried through.
        body = json.loads(captured["body"].decode("utf-8"))
        self.assertEqual("qwen2.5-7b-instruct", body["model"])
        self.assertFalse(body["stream"])
        msgs = body["messages"]
        self.assertEqual(2, len(msgs))
        self.assertEqual("system", msgs[0]["role"])
        self.assertIn("geography tutor", msgs[0]["content"])
        self.assertEqual("user", msgs[1]["role"])
        self.assertIn("capital of France", msgs[1]["content"])

    def test_invoke_model_override(self) -> None:
        """Per-call model override reaches the request body."""
        adapter = self._adapter(model="qwen2.5-7b-instruct")
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = req.data
            return _FakeResponse(_make_chat_response("ok"))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            asyncio.run(adapter.invoke("prompt", [], model="llama-3.1-8b"))

        body = json.loads(captured["body"].decode("utf-8"))
        self.assertEqual("llama-3.1-8b", body["model"])

    def test_invoke_skips_empty_context_blobs(self) -> None:
        """Empty/None context entries are dropped, not sent as empty messages."""
        adapter = self._adapter()
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = req.data
            return _FakeResponse(_make_chat_response("ok"))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            asyncio.run(adapter.invoke("prompt", ["real", "", None]))

        body = json.loads(captured["body"].decode("utf-8"))
        # 1 system (the "real" blob) + 1 user (prompt) = 2 total.
        self.assertEqual(2, len(body["messages"]))
        self.assertEqual("system", body["messages"][0]["role"])
        self.assertEqual("real", body["messages"][0]["content"])

    def test_invoke_sends_authorization_header_when_api_key_set(self) -> None:
        adapter = self._adapter(api_key="sk-test-12345")
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.header_items())
            return _FakeResponse(_make_chat_response("ok"))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            asyncio.run(adapter.invoke("prompt", []))

        # urllib normalizes header names; check case-insensitively.
        headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual("Bearer sk-test-12345", headers_lower["authorization"])

    def test_invoke_no_auth_header_when_api_key_empty(self) -> None:
        adapter = self._adapter(api_key="")
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.header_items())
            return _FakeResponse(_make_chat_response("ok"))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            asyncio.run(adapter.invoke("prompt", []))

        headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertNotIn("authorization", headers_lower)

    # ------------------------------------------------------------------
    # invoke — error paths
    # ------------------------------------------------------------------

    def test_invoke_4xx_surfaces_as_runtimeerror(self) -> None:
        """A 4xx response from LM Studio raises RuntimeError with the body."""
        adapter = self._adapter()
        err_body = b'{"error": {"message": "Model not found"}}'

        def fake_urlopen(req, timeout=None):
            # urllib raises HTTPError for 4xx/5xx by default.
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=404,
                msg="Not Found",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            )

        # We also need the HTTPError to be readable when our adapter calls
        # e.read(). The urllib.error.HTTPError __init__ accepts fp; if None,
        # read() will fail. Provide a BytesIO via a subclass.
        import io

        class _HTTPErrorWithBody(urllib.error.HTTPError):
            def __init__(self, code: int, body: bytes) -> None:
                super().__init__(
                    url="http://localhost:1234/v1/chat/completions",
                    code=code,
                    msg="Not Found",
                    hdrs=None,  # type: ignore[arg-type]
                    fp=io.BytesIO(body),
                )

        def fake_urlopen_with_body(req, timeout=None):
            raise _HTTPErrorWithBody(404, err_body)

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen_with_body):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(adapter.invoke("prompt", []))

        msg = str(ctx.exception)
        self.assertIn("404", msg)
        self.assertIn("Model not found", msg)

    def test_invoke_connection_refused_surfaces_as_runtimeerror(self) -> None:
        """If the server is down, urllib URLError is wrapped in RuntimeError."""
        adapter = self._adapter()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("Connection refused")

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(adapter.invoke("prompt", []))
        self.assertIn("lmstudio", str(ctx.exception))
        self.assertIn("Connection refused", str(ctx.exception))

    def test_invoke_invalid_json_response_raises(self) -> None:
        """If the server returns garbage, RuntimeError fires (not silent None)."""
        adapter = self._adapter()

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(b"<html>not json</html>")

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(adapter.invoke("prompt", []))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_invoke_missing_choices_raises(self) -> None:
        """Malformed JSON (no choices[]) surfaces as RuntimeError."""
        adapter = self._adapter()

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(b'{"object": "unexpected"}')

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(adapter.invoke("prompt", []))
        self.assertIn("choices[0].message.content", str(ctx.exception))

    def test_invoke_timeout_passes_through_as_asyncio_timeouterror(self) -> None:
        """A slow urllib call exceeds wait_for and raises asyncio.TimeoutError.

        The adapter runs ``_do_post`` in a worker thread via
        ``asyncio.to_thread`` and gates it with ``asyncio.wait_for`` set to
        the configured ``timeout_seconds``. We validate the gate by patching
        ``_do_post`` with a slow synchronous function and asserting the
        public contract: a slow call surfaces as ``asyncio.TimeoutError``.
        """
        adapter = self._adapter(timeout_seconds=0.1)

        def slow_do_post(req, timeout):
            import time as _time

            # Sleep > wait_for budget (0.1s). The thread will keep running
            # in the background until it returns, but the caller sees
            # asyncio.TimeoutError as soon as the outer gate fires.
            _time.sleep(2.0)
            return "unreached"

        with patch("agent_council.runtimes.lmstudio._do_post", new=slow_do_post):
            with self.assertRaises(asyncio.TimeoutError):
                asyncio.run(adapter.invoke("prompt", []))

    # ------------------------------------------------------------------
    # health_check
    # ------------------------------------------------------------------

    def test_health_check_true_when_model_listed(self) -> None:
        adapter = self._adapter(model="qwen2.5-7b-instruct")

        def fake_urlopen(req, timeout=None):
            self.assertEqual("GET", req.get_method())
            self.assertEqual("http://localhost:1234/v1/models", req.full_url)
            return _FakeResponse(_make_models_response([
                "qwen2.5-7b-instruct", "llama-3.1-8b",
            ]))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            self.assertTrue(adapter.health_check())

    def test_health_check_false_when_model_not_listed(self) -> None:
        adapter = self._adapter(model="qwen2.5-7b-instruct")

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(_make_models_response(["mistral-7b"]))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            self.assertFalse(adapter.health_check())

    def test_health_check_false_when_server_unreachable(self) -> None:
        adapter = self._adapter()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("Connection refused")

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            self.assertFalse(adapter.health_check())

    def test_health_check_true_when_no_model_configured_and_any_loaded(self) -> None:
        """No model declared in config → pass if at least one model is loaded."""
        adapter = self._adapter(model="")

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(_make_models_response(["some-model"]))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            self.assertTrue(adapter.health_check())

    def test_health_check_false_when_no_model_configured_and_none_loaded(self) -> None:
        adapter = self._adapter(model="")

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(_make_models_response([]))

        with patch("agent_council.runtimes.lmstudio.urllib.request.urlopen",
                   new=fake_urlopen):
            self.assertFalse(adapter.health_check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
