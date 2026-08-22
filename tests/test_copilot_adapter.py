"""Unit tests for CopilotCLIAdapter — GitHub Copilot CLI runtime adapter.

We don't shell out to the real ``copilot`` binary (not assumed installed in CI
or on every developer machine). Instead we drive the adapter through a
monkey-patched ``asyncio.create_subprocess_exec`` to assert the contract:

  - args contract: the composed prompt is passed as the **final arg after -p**
    (Copilot takes the prompt as an argument, NOT via stdin — unlike claude/ollama)
  - stdin is NOT used: ``communicate`` receives no input bytes
  - model override reaches ``--model``
  - configured flags are forwarded verbatim
  - timeout: raises asyncio.TimeoutError and kills the proc when exceeded
  - nonzero exit: raises RuntimeError with ``copilot`` + stderr in the message
  - health_check returns True/False based on PATH + --version exit code
  - adapter_name is "copilot_cli"
  - the registry resolves ``type: copilot_cli`` to CopilotCLIAdapter
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
from agent_council.runtimes.copilot_cli import CopilotCLIAdapter  # noqa: E402


class _FakeProc:
    """Minimal stand-in for an asyncio subprocess Process."""

    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout_bytes = stdout
        self.stderr_bytes = stderr
        self.returncode = returncode
        self.kill_called = False
        self.stdin_bytes_received: bytes | None = None
        self.communicate_called = False

    async def communicate(self, stdin_bytes: bytes | None = None) -> tuple[bytes, bytes]:
        self.communicate_called = True
        self.stdin_bytes_received = stdin_bytes
        return self.stdout_bytes, self.stderr_bytes

    def kill(self) -> None:
        self.kill_called = True


class _HangingProc(_FakeProc):
    """Fake proc whose communicate() hangs longer than the timeout."""

    async def communicate(self, stdin_bytes: bytes | None = None) -> tuple[bytes, bytes]:
        await asyncio.sleep(10)
        return b"", b""


class CopilotCLIAdapterTest(unittest.TestCase):
    """Contract tests for the copilot_cli runtime adapter."""

    def _adapter(self, **overrides) -> CopilotCLIAdapter:
        cfg = {
            "binary": "copilot",
            "model": "",
            "flags": ["-s", "--no-color", "--no-custom-instructions"],
            "invocation_pattern": "args",
            "timeout_seconds": 30,
        }
        cfg.update(overrides)
        return CopilotCLIAdapter(cfg)

    def test_adapter_name(self) -> None:
        self.assertEqual("copilot_cli", self._adapter().adapter_name())

    def test_registry_resolves_copilot_cli(self) -> None:
        adapter = build_adapter({"type": "copilot_cli", "model": "auto"})
        self.assertIsInstance(adapter, CopilotCLIAdapter)

    def test_invoke_passes_prompt_as_arg_not_stdin(self) -> None:
        """Composed prompt is the final arg after -p; stdin is not used."""
        adapter = self._adapter()
        fake = _FakeProc(stdout=b"hello from copilot\n")
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = list(args)
            captured["kwargs"] = kwargs
            return fake

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            out = asyncio.run(adapter.invoke("hello world", ["context blob"]))

        self.assertEqual("hello from copilot\n", out)
        args = captured["args"]
        self.assertEqual("copilot", args[0])
        # -p must be present, and the composed prompt must be the final arg.
        self.assertIn("-p", args)
        self.assertEqual("-p", args[-2])
        composed = args[-1]
        self.assertIn("context blob", composed)
        self.assertIn("hello world", composed)
        # Prompt is passed as an arg — nothing is piped to stdin.
        self.assertIsNone(fake.stdin_bytes_received)

    def test_invoke_respects_model_override(self) -> None:
        adapter = self._adapter(model="")
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = list(args)
            return _FakeProc(stdout=b"ok")

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            asyncio.run(adapter.invoke("prompt", [], model="claude-sonnet-4.5"))

        args = captured["args"]
        self.assertIn("--model", args)
        self.assertEqual("claude-sonnet-4.5", args[args.index("--model") + 1])

    def test_invoke_appends_extra_flags(self) -> None:
        adapter = self._adapter(flags=["-s", "--no-color", "--disable-builtin-mcps"])
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = list(args)
            return _FakeProc(stdout=b"ok")

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            asyncio.run(adapter.invoke("prompt", []))

        self.assertIn("-s", captured["args"])
        self.assertIn("--no-color", captured["args"])
        self.assertIn("--disable-builtin-mcps", captured["args"])

    def test_invoke_does_not_duplicate_model_flag(self) -> None:
        """If --model is already in flags, the adapter must not add a second one."""
        adapter = self._adapter(flags=["-s", "--model", "auto"])
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = list(args)
            return _FakeProc(stdout=b"ok")

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            asyncio.run(adapter.invoke("prompt", [], model="gpt-5"))

        self.assertEqual(1, captured["args"].count("--model"))

    def test_invoke_raises_runtimeerror_on_nonzero_exit(self) -> None:
        adapter = self._adapter()
        fake = _FakeProc(stdout=b"", stderr=b"not authenticated", returncode=1)

        async def fake_create_subprocess_exec(*args, **kwargs):
            return fake

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(adapter.invoke("prompt", []))
        self.assertIn("copilot", str(ctx.exception))
        self.assertIn("not authenticated", str(ctx.exception))

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
            stdout = "copilot version 0.1.0"
            stderr = ""

        with patch("shutil.which", return_value="/usr/local/bin/copilot"), \
             patch("subprocess.run", return_value=FakeRes()):
            self.assertTrue(adapter.health_check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
