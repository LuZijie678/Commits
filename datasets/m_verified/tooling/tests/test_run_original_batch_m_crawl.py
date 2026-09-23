import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_original_batch_m_crawl.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_original_batch_m_crawl", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RunCmdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_run_cmd_binds_explicit_child_stdio(self) -> None:
        recorded: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            recorded["args"] = args
            recorded["kwargs"] = kwargs
            return subprocess.CompletedProcess(args[0], 0)

        with patch.object(self.module.subprocess, "run", side_effect=fake_run):
            self.module.run_cmd(["python3", "-c", "print(123)"], Path.cwd(), {})

        kwargs = recorded["kwargs"]
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("stdout", kwargs)
        self.assertIn("stderr", kwargs)
        self.assertIsNotNone(kwargs["stdout"])
        self.assertIsNotNone(kwargs["stderr"])

    def test_run_cmd_executes_python_scripts_in_process(self) -> None:
        script_path = SCRIPT_PATH.parent / "discover_high_star_repos.py"

        with (
            patch.object(self.module.runpy, "run_path") as run_path,
            patch.object(self.module.subprocess, "run") as subprocess_run,
        ):
            self.module.run_cmd([sys.executable, str(script_path), "--help"], Path.cwd(), {"GITHUB_TOKEN": "token"})

        run_path.assert_called_once_with(str(script_path), run_name="__main__")
        subprocess_run.assert_not_called()

    def test_resolve_discovery_query_file_uses_explicit_query_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            explicit = data_dir / "explicit_queries.txt"
            explicit.write_text("stars:1000..2000 fork:false archived:false language:Elixir\n", encoding="utf-8")

            class Args:
                query_file = explicit
                auto_relaxed_query_after_empty_streak = 2

            query_file, strategy = self.module.resolve_discovery_query_file(Args(), data_dir, {"empty_discovery_streak": 5})

        self.assertEqual(query_file, explicit)
        self.assertEqual(strategy, "explicit_query_file")

    def test_resolve_discovery_query_file_generates_relaxed_queries_after_empty_streak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)

            class Args:
                query_file = None
                auto_relaxed_query_after_empty_streak = 2
                auto_relaxed_query_after_low_yield_streak = 2
                low_yield_target_threshold = 1

            query_file, strategy = self.module.resolve_discovery_query_file(Args(), data_dir, {"empty_discovery_streak": 2})

            self.assertIsNotNone(query_file)
            assert query_file is not None
            self.assertTrue(query_file.exists())
            text = query_file.read_text(encoding="utf-8")

        self.assertEqual(strategy, "auto_relaxed_query_file")
        self.assertIn("language:Elixir", text)
        self.assertIn("topic:developer-tools", text)

    def test_resolve_discovery_query_file_stays_default_before_empty_streak_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)

            class Args:
                query_file = None
                auto_relaxed_query_after_empty_streak = 2
                auto_relaxed_query_after_low_yield_streak = 2
                low_yield_target_threshold = 1

            query_file, strategy = self.module.resolve_discovery_query_file(Args(), data_dir, {"empty_discovery_streak": 1})

        self.assertIsNone(query_file)
        self.assertEqual(strategy, "default_queries")

    def test_resolve_discovery_query_file_generates_relaxed_queries_after_low_yield_streak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)

            class Args:
                query_file = None
                auto_relaxed_query_after_empty_streak = 2
                auto_relaxed_query_after_low_yield_streak = 2
                low_yield_target_threshold = 1

            query_file, strategy = self.module.resolve_discovery_query_file(
                Args(),
                data_dir,
                {"empty_discovery_streak": 0, "low_yield_discovery_streak": 2},
            )

            self.assertIsNotNone(query_file)
            assert query_file is not None
            self.assertTrue(query_file.exists())

        self.assertEqual(strategy, "auto_relaxed_query_file")

    def test_infer_empty_discovery_streak_counts_trailing_empty_campaigns(self) -> None:
        state = {
            "campaigns": [
                {"prefix": "a", "target_count": 12},
                {"prefix": "b", "target_count": 0},
                {"prefix": "c", "target_count": 0},
                {"prefix": "d", "target_count": 0},
            ]
        }

        self.assertEqual(self.module.infer_empty_discovery_streak(state), 3)

    def test_infer_low_yield_discovery_streak_counts_trailing_low_yield_campaigns(self) -> None:
        state = {
            "campaigns": [
                {"prefix": "a", "target_count": 12},
                {"prefix": "b", "target_count": 1},
                {"prefix": "c", "target_count": 0},
                {"prefix": "d", "target_count": 1},
            ]
        }

        self.assertEqual(self.module.infer_low_yield_discovery_streak(state, 1), 3)


if __name__ == "__main__":
    unittest.main()
