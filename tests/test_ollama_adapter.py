"""Unit tests for OllamaAdapter — D1, second runtime adapter.

We don't shell out to real ollama (not assumed installed in CI or developer
machines). Instead, we drive the adapter through monkey-patched
``asyncio.create_subprocess_exec`` to assert the contract:

  - stdin contract: full prompt is encoded as UTF-8 and piped to stdin
  - args: ``ollama run <model>`` with optional flags
  - timeout: raises asyncio.TimeoutError when exceeded
  - nonzero exit: raises RuntimeError with stderr in the message
  - health_check returns True/False based on PATH + --version exit code
  - adapter_name is "ollama"
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.runtimes import build_adapter  # noqa: E402
from agent_council.runtimes.ollama import OllamaAdapter  # noqa: E402


class _FakeProc:
    """Minimal stand-in for asyncio subprocess Process."""

    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout_bytes = stdout
        self.stderr_bytes = stderr
        self.returncode = returncode
        self.kill_called = False
        self.stdin_bytes_received: bytes | None = None

    async def communicate(self, stdin_bytes: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin_bytes_received = stdin_bytes
        return self.stdout_bytes, self.stderr_bytes

    def kill(self) -> None:
        self.kill_called = True


class _HangingProc(_FakeProc):
    """Fake proc whose communicate() hangs longer than the timeout."""

    async def communicate(self, stdin_bytes: bytes | None = None) -> tuple[bytes, bytes]:
        # Sleep beyond the test's timeout — the wait_for in invoke() will raise.
        await asyncio.sleep(10)
        return b"", b""


class OllamaAdapterTest(unittest.TestCase):
    """Contract tests for the ollama runtime adapter."""

    def _adapter(self, **overrides) -> OllamaAdapter:
        cfg = {
            "binary": "ollama",
            "model": "llama3.1",
            "flags": [],
            "invocation_pattern": "stdin",
            "timeout_seconds": 30,
        }
        cfg.update(overrides)
        return OllamaAdapter(cfg)

    def test_adapter_name(self) -> None:
        self.assertEqual("ollama", self._adapter().adapter_name())

    def test_registry_resolves_ollama(self) -> None:
        adapter = build_adapter({"type": "ollama", "model": "llama3.1"})
        self.assertIsInstance(adapter, OllamaAdapter)

    def test_registry_resolves_gh_models(self) -> None:
        """Documented fallback should resolve even though invoke() raises."""
        from agent_council.runtimes.gh_models import GhModelsAdapter

        adapter = build_adapter({"type": "gh_models", "model": "gpt-4o-mini"})
        self.assertIsInstance(adapter, GhModelsAdapter)

    def test_invoke_pipes_full_prompt_to_stdin(self) -> None:
        """Composed prompt is encoded UTF-8 and piped to subprocess stdin."""
        adapter = self._adapter()
        fake = _FakeProc(stdout=b"hello from ollama\n")

        async def fake_create_subprocess_exec(*args, **kwargs):
            self.assertEqual(args[0], "ollama")
            self.assertEqual(args[1], "run")
            self.assertEqual(args[2], "llama3.1")
            return fake

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            out = asyncio.run(adapter.invoke("hello world", ["context blob"]))

        self.assertEqual("hello from ollama\n", out)
        self.assertIsNotNone(fake.stdin_bytes_received)
        decoded = fake.stdin_bytes_received.decode("utf-8")
        self.assertIn("context blob", decoded)
        self.assertIn("hello world", decoded)

    def test_invoke_respects_model_override(self) -> None:
        adapter = self._adapter(model="llama3.1")
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProc(stdout=b"ok")

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            asyncio.run(adapter.invoke("prompt", [], model="qwen2.5"))

        # Model override must reach the positional arg.
        self.assertEqual("qwen2.5", captured["args"][2])

    def test_invoke_appends_extra_flags(self) -> None:
        adapter = self._adapter(flags=["--keepalive", "5m"])
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = list(args)
            return _FakeProc(stdout=b"ok")

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            asyncio.run(adapter.invoke("prompt", []))

        self.assertIn("--keepalive", captured["args"])
        self.assertIn("5m", captured["args"])

    def test_invoke_raises_runtimeerror_on_nonzero_exit(self) -> None:
        adapter = self._adapter()
        fake = _FakeProc(stdout=b"", stderr=b"model not found", returncode=1)

        async def fake_create_subprocess_exec(*args, **kwargs):
            return fake

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(adapter.invoke("prompt", []))
        self.assertIn("ollama", str(ctx.exception))
        self.assertIn("model not found", str(ctx.exception))

    def test_invoke_raises_timeout_and_kills_proc(self) -> None:
        adapter = self._adapter(timeout_seconds=0.05)
        fake = _HangingProc(stdout=b"")

        async def fake_create_subprocess_exec(*args, **kwargs):
            return fake

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            with self.assertRaises(asyncio.TimeoutError):
                asyncio.run(adapter.invoke("prompt", []))
        self.assertTrue(fake.kill_called, "kill() should be called on timeout")

    def test_health_check_returns_false_when_binary_missing(self) -> None:
        adapter = self._adapter(binary="this_binary_does_not_exist_xyz")
        self.assertFalse(adapter.health_check())

    def test_health_check_via_mocked_subprocess(self) -> None:
        """When binary exists and --version exits 0, health_check returns True."""
        adapter = self._adapter()

        class FakeRes:
            returncode = 0
            stdout = "ollama version 0.1.0"
            stderr = ""

        with patch("shutil.which", return_value="/usr/bin/ollama"), \
             patch("subprocess.run", return_value=FakeRes()):
            self.assertTrue(adapter.health_check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
