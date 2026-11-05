"""Subprocess reliability checks with mocks or a harmless local Python child."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_council.config import load_config
from agent_council.orchestrator import Council
from agent_council.runtimes.claude_cli import ClaudeCLIAdapter
from agent_council.runtimes.ollama import OllamaAdapter


class Process:
    def __init__(self, *, hang=False, returncode=0, stdout=b"ok", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.hang = hang
        self.started = asyncio.Event()
        self.exited = asyncio.Event()
        self.killed = False
        self.drained = False
        self.input = None

    async def communicate(self, data=None):
        self.input = data
        self.started.set()
        if self.hang:
            await self.exited.wait()
        self.drained = True
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.exited.set()


class RuntimeProcessTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_kills_and_drains_each_subprocess_adapter(self):
        for adapter_type in (ClaudeCLIAdapter, OllamaAdapter):
            with self.subTest(adapter=adapter_type.__name__):
                proc = Process(hang=True)
                with patch("asyncio.create_subprocess_exec", return_value=proc):
                    with self.assertRaises(asyncio.TimeoutError):
                        await adapter_type({"timeout_seconds": 0.01}).invoke("prompt", [])
                self.assertTrue(proc.killed)
                self.assertTrue(proc.drained)

    async def test_cancellation_kills_and_drains_before_propagating(self):
        for adapter_type in (ClaudeCLIAdapter, OllamaAdapter):
            with self.subTest(adapter=adapter_type.__name__):
                proc = Process(hang=True)
                with patch("asyncio.create_subprocess_exec", return_value=proc):
                    task = asyncio.create_task(adapter_type({}).invoke("prompt", []))
                    await proc.started.wait()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertTrue(proc.killed)
                self.assertTrue(proc.drained)

    async def test_expected_launch_errors_are_runtime_failures(self):
        for adapter_type in (ClaudeCLIAdapter, OllamaAdapter):
            with self.subTest(adapter=adapter_type.__name__):
                with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError(2, "missing executable")):
                    with self.assertRaisesRegex(RuntimeError, "could not start"):
                        await adapter_type({}).invoke("prompt", [])

    async def test_programming_errors_are_not_disguised_as_runtime_failures(self):
        failure = ValueError("unexpected adapter programming error")
        with patch("asyncio.create_subprocess_exec", side_effect=failure):
            with self.assertRaises(ValueError) as raised:
                await ClaudeCLIAdapter({}).invoke("prompt", [])
        self.assertIs(failure, raised.exception)

    async def test_nonzero_exit_and_utf8_output(self):
        adapter = ClaudeCLIAdapter({})
        with patch("asyncio.create_subprocess_exec", return_value=Process(returncode=1, stderr=b"not authenticated")):
            with self.assertRaisesRegex(RuntimeError, "not authenticated"):
                await adapter.invoke("prompt", [])
        proc = Process(stdout="caf\u00e9".encode("utf-8"))
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            self.assertEqual("caf\u00e9", await adapter.invoke("na\u00efve", ["context"]))
        self.assertIn("na\u00efve".encode("utf-8"), proc.input)

    async def test_large_unicode_prompt_uses_stdin_without_truncation(self):
        prompt = "Review this sentence: \u03c0.\n" * 6000
        response = await ClaudeCLIAdapter({"timeout_seconds": 10}).run_subprocess(
            [sys.executable, "-I", "-c", "import sys; print(len(sys.stdin.buffer.read().decode('utf-8')))"],
            prompt,
        )
        self.assertEqual(len(prompt), int(response))

    async def test_cancelling_a_real_local_child_waits_for_its_exit(self):
        create = asyncio.create_subprocess_exec
        started = asyncio.Event()
        processes = []

        async def spawn(*args, **kwargs):
            process = await create(*args, **kwargs)
            processes.append(process)
            started.set()
            return process

        try:
            with patch("asyncio.create_subprocess_exec", spawn):
                task = asyncio.create_task(ClaudeCLIAdapter({}).run_subprocess(
                    [sys.executable, "-I", "-c", "import time; time.sleep(60)"]
                ))
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNotNone(processes[0].returncode)
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    async def test_windows_argument_guard_fails_before_spawning(self):
        adapter = ClaudeCLIAdapter({})
        with patch("agent_council.runtimes.base.sys.platform", "win32"), \
             patch("asyncio.create_subprocess_exec") as spawn:
            with self.assertRaisesRegex(RuntimeError, "Windows command-line limit"):
                await adapter.run_subprocess(["runtime", "-p", "x" * 33000])
            spawn.assert_not_called()

    async def test_windows_guard_counts_utf16_units_for_non_bmp_text(self):
        with patch("agent_council.runtimes.base.sys.platform", "win32"), \
             patch("asyncio.create_subprocess_exec") as spawn:
            with self.assertRaisesRegex(RuntimeError, "Windows command-line limit"):
                await ClaudeCLIAdapter({}).run_subprocess(["runtime", "\U0001f600" * 17000])
            spawn.assert_not_called()

    async def test_invalid_timeout_does_not_spawn(self):
        for seconds in (0, -1, float("nan"), float("inf")):
            with self.subTest(seconds=seconds):
                with patch("asyncio.create_subprocess_exec") as spawn:
                    with self.assertRaisesRegex(ValueError, "finite and positive"):
                        await ClaudeCLIAdapter({"timeout_seconds": seconds}).invoke("prompt", [])
                    spawn.assert_not_called()

    async def test_explicit_model_overrides_both_configured_flag_forms(self):
        for flags in (["--print", "--model", "old"], ["--print", "--model=old"]):
            with self.subTest(flags=flags):
                adapter = ClaudeCLIAdapter({"model": "configured", "flags": flags})
                with patch("asyncio.create_subprocess_exec", return_value=Process()) as spawn:
                    await adapter.invoke("prompt", [], model="requested")
                args = list(spawn.call_args.args)
                self.assertEqual(["claude", "--print", "--model", "requested"], args)
                self.assertEqual(flags, adapter.flags)

    async def test_without_override_configured_model_flag_still_wins(self):
        adapter = ClaudeCLIAdapter({"model": "configured", "flags": ["--print", "--model=flag"]})
        with patch("asyncio.create_subprocess_exec", return_value=Process()) as spawn:
            await adapter.invoke("prompt", [])
        self.assertEqual(("claude", "--print", "--model=flag"), spawn.call_args.args)

    async def test_unrelated_flag_prefix_does_not_hide_default_model(self):
        adapter = ClaudeCLIAdapter({"model": "configured", "flags": ["--model-info"]})
        with patch("asyncio.create_subprocess_exec", return_value=Process()) as spawn:
            await adapter.invoke("prompt", [])
        self.assertEqual(("claude", "--model-info", "--model", "configured"), spawn.call_args.args)

    async def test_missing_binary_produces_audited_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = load_config(ROOT / "tests" / "council.example.yaml")
            config["logging"] = {"log_path": str(folder / "log.jsonl"), "archive_dir": str(folder / "archive")}
            adapter = ClaudeCLIAdapter({"binary": str(folder / "missing-executable")})
            result = await Council(config, ROOT / "tests", adapter=adapter).run(ROOT / "tests" / "sample_artifact.md")
            self.assertEqual("INCOMPLETE", result.verdict)
            self.assertIn("could not start", result.adjudicator_error)
            record = json.loads((folder / "log.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(result.adjudicator_error, record["adjudicator_error"])
            self.assertTrue((folder / "archive" / result.span_id / "artifact.md").exists())


if __name__ == "__main__":
    unittest.main()
