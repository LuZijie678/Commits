import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_continuous_hard_b_recovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_continuous_hard_b_recovery", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ContinuousHardBRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_inspect_need_diff_file_detects_lfs_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hard_b_need_full_diff.csv"
            path.write_text(
                "version https://git-lfs.github.com/spec/v1\n"
                "oid sha256:abc\n"
                "size 123\n",
                encoding="utf-8",
            )

            snapshot = self.module.inspect_need_diff_file(path)

        self.assertEqual(snapshot["status"], "lfs_pointer")
        self.assertEqual(snapshot["rows"], 0)
        self.assertEqual(snapshot["sha256"], "")

    def test_should_run_recovery_when_backlog_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_csv = root / "hard_b_need_full_diff.csv"
            output_csv = root / "hard_b_full_diff_recovery_batch.csv"
            output_jsonl = root / "hard_b_full_diff_recovery_batch.jsonl"
            summary = root / "hard_b_full_diff_recovery_batch_summary.json"
            input_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
            output_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
            output_jsonl.write_text('{"repo":"foo/bar","sha":"abc"}\n', encoding="utf-8")
            summary.write_text("{}", encoding="utf-8")

            snapshot = self.module.inspect_need_diff_file(input_csv)
            state = {"last_recovery_input_sha256": "different"}

            self.assertTrue(self.module.should_run_recovery(snapshot, state, output_csv, output_jsonl, summary))

    def test_should_skip_recovery_when_backlog_unchanged_and_outputs_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_csv = root / "hard_b_need_full_diff.csv"
            output_csv = root / "hard_b_full_diff_recovery_batch.csv"
            output_jsonl = root / "hard_b_full_diff_recovery_batch.jsonl"
            summary = root / "hard_b_full_diff_recovery_batch_summary.json"
            input_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
            output_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
            output_jsonl.write_text('{"repo":"foo/bar","sha":"abc"}\n', encoding="utf-8")
            summary.write_text("{}", encoding="utf-8")
            summary.touch()

            snapshot = self.module.inspect_need_diff_file(input_csv)
            summary.touch()
            state = {"last_recovery_input_sha256": snapshot["sha256"]}

            self.assertFalse(self.module.should_run_recovery(snapshot, state, output_csv, output_jsonl, summary))

    def test_should_skip_recovery_when_only_backlog_mtime_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_csv = root / "hard_b_need_full_diff.csv"
            output_csv = root / "hard_b_full_diff_recovery_batch.csv"
            output_jsonl = root / "hard_b_full_diff_recovery_batch.jsonl"
            summary = root / "hard_b_full_diff_recovery_batch_summary.json"
            input_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
            output_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
            output_jsonl.write_text('{"repo":"foo/bar","sha":"abc"}\n', encoding="utf-8")
            summary.write_text("{}", encoding="utf-8")

            snapshot = self.module.inspect_need_diff_file(input_csv)
            state = {"last_recovery_input_sha256": snapshot["sha256"]}
            input_csv.touch()
            newer_snapshot = self.module.inspect_need_diff_file(input_csv)

            self.assertFalse(self.module.should_run_recovery(newer_snapshot, state, output_csv, output_jsonl, summary))

    def test_run_loop_once_records_empty_backlog_without_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            need_diff_csv = root / "hard_b_need_full_diff.csv"
            state = {}
            args = argparse.Namespace(
                need_diff_csv=need_diff_csv,
                recovery_output_csv=root / "hard_b_full_diff_recovery_batch.csv",
                recovery_output_jsonl=root / "hard_b_full_diff_recovery_batch.jsonl",
                recovery_summary=root / "hard_b_full_diff_recovery_batch_summary.json",
                sleep_seconds=30,
            )

            def fake_run_build(passed_args, passed_root):
                self.assertEqual(passed_root, root)
                need_diff_csv.write_text("repo,sha\n", encoding="utf-8")

            def fake_run_recovery(_passed_args, _passed_root):
                raise AssertionError("recovery should not run for empty backlog")

            with (
                patch.object(self.module, "run_build", side_effect=fake_run_build),
                patch.object(self.module, "run_recovery", side_effect=fake_run_recovery),
            ):
                updated = self.module.run_loop_once(args, root, state)

        self.assertEqual(updated["last_status"], "empty_backlog")
        self.assertEqual(updated["need_diff_rows"], 0)
        self.assertFalse(updated["recovery_triggered"])
        self.assertEqual(updated["sleep_seconds"], 30)
        self.assertEqual(updated["last_error"], "")

    def test_run_loop_once_records_recovery_summary_when_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            need_diff_csv = root / "hard_b_need_full_diff.csv"
            recovery_summary = root / "hard_b_full_diff_recovery_batch_summary.json"
            state = {"last_recovery_input_sha256": ""}
            args = argparse.Namespace(
                need_diff_csv=need_diff_csv,
                recovery_output_csv=root / "hard_b_full_diff_recovery_batch.csv",
                recovery_output_jsonl=root / "hard_b_full_diff_recovery_batch.jsonl",
                recovery_summary=recovery_summary,
                sleep_seconds=30,
            )

            def fake_run_build(_passed_args, _passed_root):
                need_diff_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")

            def fake_run_recovery(_passed_args, _passed_root):
                args.recovery_output_csv.write_text("repo,sha\nfoo/bar,abc\n", encoding="utf-8")
                args.recovery_output_jsonl.write_text('{"repo":"foo/bar","sha":"abc"}\n', encoding="utf-8")
                recovery_summary.write_text(json.dumps({"recovered": 1}), encoding="utf-8")

            with (
                patch.object(self.module, "run_build", side_effect=fake_run_build),
                patch.object(self.module, "run_recovery", side_effect=fake_run_recovery),
            ):
                updated = self.module.run_loop_once(args, root, state)

        self.assertEqual(updated["last_status"], "recovery_completed")
        self.assertTrue(updated["recovery_triggered"])
        self.assertEqual(updated["last_recovery_input_sha256"], updated["need_diff_sha256"])
        self.assertEqual(updated["recovery_summary"]["recovered"], 1)

    def test_run_cmd_binds_explicit_child_stdio(self) -> None:
        recorded: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            recorded["args"] = args
            recorded["kwargs"] = kwargs
            return subprocess.CompletedProcess(args[0], 0)

        with patch.object(self.module.subprocess, "run", side_effect=fake_run):
            self.module.run_cmd(["python3", "-c", "print(123)"], Path.cwd())

        kwargs = recorded["kwargs"]
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("stdout", kwargs)
        self.assertIn("stderr", kwargs)
        self.assertIsNotNone(kwargs["stdout"])
        self.assertIsNotNone(kwargs["stderr"])

    def test_parse_args_defaults_recovery_diff_max_chars_to_zero(self) -> None:
        with patch.object(
            self.module.sys,
            "argv",
            ["run_continuous_hard_b_recovery.py"],
        ):
            args = self.module.parse_args()

        self.assertEqual(args.recovery_diff_max_chars, 0)

    def test_parse_args_defaults_to_non_daemon_mode(self) -> None:
        with patch.object(
            self.module.sys,
            "argv",
            ["run_continuous_hard_b_recovery.py"],
        ):
            args = self.module.parse_args()

        self.assertFalse(args.daemon)
        self.assertFalse(args.one_round)

    def test_parse_args_accepts_daemon_flag(self) -> None:
        with patch.object(
            self.module.sys,
            "argv",
            ["run_continuous_hard_b_recovery.py", "--daemon"],
        ):
            args = self.module.parse_args()

        self.assertTrue(args.daemon)


if __name__ == "__main__":
    unittest.main()
