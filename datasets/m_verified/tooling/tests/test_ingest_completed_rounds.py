import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest_completed_rounds.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ingest_completed_rounds", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class IngestCompletedRoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_collect_unlabeled_rows_dedupes_and_skips_existing_keys(self) -> None:
        header = "repo,sha,subject,diff_status,git_diff\n"
        row_a = "owner/repo,aaa,first,ok,diff --git a/a b/a\n"
        row_b = "owner/repo,aaa,duplicate,ok,diff --git a/a b/a\n"
        row_c = "owner/other,bbb,second,ok,diff --git a/b b/b\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.csv"
            second = Path(tmpdir) / "second.csv"
            first.write_text(header + row_a + row_c, encoding="utf-8")
            second.write_text(header + row_b, encoding="utf-8")

            rows = self.module.collect_unlabeled_rows(
                [first, second],
                existing_keys={("owner/other", "bbb")},
            )

        self.assertEqual([(row["repo"], row["sha"]) for row in rows], [("owner/repo", "aaa")])

    def test_parse_args_defaults_label_api_key_file(self) -> None:
        argv = sys.argv[:]
        try:
            sys.argv = ["ingest_completed_rounds.py"]
            args = self.module.parse_args()
        finally:
            sys.argv = argv

        self.assertEqual(args.label_api_key_file.name, ".llm_api_key")

    def test_load_module_handles_large_csv_fields(self) -> None:
        huge_diff = "diff --git a/a b/a\n" + ("x" * 200_000)
        header = "repo,sha,subject,diff_status,git_diff\n"
        row = f"owner/repo,aaa,first,ok,\"{huge_diff}\"\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "large.csv"
            csv_path.write_text(header + row, encoding="utf-8")

            csv.field_size_limit(131_072)
            module = load_module()
            rows = module.read_csv(csv_path)

        self.assertEqual(rows[0]["git_diff"], huge_diff)

    def test_main_passes_input_paths_as_extra_csvs_to_builders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_csv = root / "new_remote_diff.csv"
            default_glob_csv = root / "archive" / "crawl_rounds" / "m_verified" / "old_remote_diff.csv"
            input_csv.write_text(
                "repo,sha,subject,diff_status,git_diff\nowner/repo,abc,subject,ok,diff --git a/a b/a\n",
                encoding="utf-8",
            )
            default_glob_csv.parent.mkdir(parents=True, exist_ok=True)
            default_glob_csv.write_text(
                "repo,sha,subject,diff_status,git_diff\nowner/old,def,subject,ok,diff --git a/b b/b\n",
                encoding="utf-8",
            )

            labels_dir = root / "labels"
            work_dir = root / "work"
            combined_csv = root / "combined.csv"
            m_candidates_csv = root / "m_candidates.csv"
            crawl_root = root / "crawl_root"
            repos_dir = root / "repos"
            blocklist = root / "blocklist.txt"
            m_output_csv = root / "usable_m.csv"
            m_output_jsonl = root / "usable_m.jsonl"
            m_missing_csv = root / "m_missing.csv"
            m_manifest = root / "usable_m_manifest.json"
            hard_b_out_dir = root / "hard_b"
            hard_b_output_csv = root / "usable_hard_b.csv"
            hard_b_output_jsonl = root / "usable_hard_b.jsonl"
            hard_b_manifest = root / "usable_hard_b_manifest.json"
            hard_b_need_diff_csv = root / "hard_b_need_diff.csv"
            hard_b_candidates_csv = root / "hard_b_candidates.csv"
            hard_b_review_sample_csv = root / "hard_b_review_sample.csv"
            hard_b_checklist_md = root / "hard_b_checklist.md"
            summary = root / "summary.json"

            labels_dir.mkdir(parents=True, exist_ok=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            crawl_root.mkdir(parents=True, exist_ok=True)
            repos_dir.mkdir(parents=True, exist_ok=True)
            hard_b_out_dir.mkdir(parents=True, exist_ok=True)
            blocklist.write_text("", encoding="utf-8")
            combined_csv.write_text("", encoding="utf-8")

            argv = sys.argv[:]
            commands: list[list[str]] = []
            evidence_root = root / "workspace_evidence"
            try:
                sys.argv = [
                    "ingest_completed_rounds.py",
                    "--input-csv", str(input_csv),
                    "--labels-dir", str(labels_dir),
                    "--work-dir", str(work_dir),
                    "--combined-csv", str(combined_csv),
                    "--m-candidates-csv", str(m_candidates_csv),
                    "--crawl-root", str(crawl_root),
                    "--evidence-root", str(evidence_root),
                    "--repos-dir", str(repos_dir),
                    "--blocklist", str(blocklist),
                    "--m-output-csv", str(m_output_csv),
                    "--m-output-jsonl", str(m_output_jsonl),
                    "--m-missing-csv", str(m_missing_csv),
                    "--m-manifest", str(m_manifest),
                    "--hard-b-out-dir", str(hard_b_out_dir),
                    "--hard-b-output-csv", str(hard_b_output_csv),
                    "--hard-b-output-jsonl", str(hard_b_output_jsonl),
                    "--hard-b-manifest", str(hard_b_manifest),
                    "--hard-b-need-diff-csv", str(hard_b_need_diff_csv),
                    "--hard-b-candidates-csv", str(hard_b_candidates_csv),
                    "--hard-b-review-sample-csv", str(hard_b_review_sample_csv),
                    "--hard-b-checklist-md", str(hard_b_checklist_md),
                    "--summary", str(summary),
                    "--batch-name", "test_batch",
                ]

                def fake_run_cmd(cmd, cwd):
                    command = [str(part) for part in cmd]
                    commands.append(command)
                    if any(part.endswith("label_m_candidate_batches.py") for part in command):
                        output_csv = Path(command[command.index("--output-csv") + 1])
                        output_jsonl = Path(command[command.index("--output-jsonl") + 1])
                        summary_path = Path(command[command.index("--summary") + 1])
                        output_csv.write_text(
                            "repo,sha,llm_label\nowner/repo,abc,M\n",
                            encoding="utf-8",
                        )
                        output_jsonl.write_text("", encoding="utf-8")
                        summary_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
                    elif any(part.endswith("combine_gitlog_labels.py") for part in command):
                        m_csv = Path(command[command.index("--output-m") + 1])
                        combined = Path(command[command.index("--output-combined") + 1])
                        m_csv.write_text("repo,sha,llm_label\nowner/repo,abc,M\n", encoding="utf-8")
                        combined.write_text("repo,sha,llm_label\nowner/repo,abc,M\n", encoding="utf-8")

                with patch.object(self.module, "repo_root", return_value=root), patch.object(self.module, "run_cmd", side_effect=fake_run_cmd):
                    self.module.main()
            finally:
                sys.argv = argv

        build_m_cmd = next(cmd for cmd in commands if any(part.endswith("build_usable_m_diff_dataset.py") for part in cmd))
        build_hard_b_cmd = next(cmd for cmd in commands if any(part.endswith("build_hard_b_pool.py") for part in cmd))
        combine_cmd = next(cmd for cmd in commands if any(part.endswith("combine_gitlog_labels.py") for part in cmd))
        self.assertIn("--extra-csv", build_m_cmd)
        self.assertIn(str(input_csv), build_m_cmd)
        self.assertNotIn(str(default_glob_csv), build_m_cmd)
        self.assertEqual(build_m_cmd[build_m_cmd.index("--raw-dir") + 1], str(evidence_root))
        self.assertIn("--extra-csv", build_hard_b_cmd)
        self.assertIn(str(input_csv), build_hard_b_cmd)
        self.assertNotIn(str(default_glob_csv), build_hard_b_cmd)
        self.assertEqual(build_hard_b_cmd[build_hard_b_cmd.index("--raw-dir") + 1], str(evidence_root))
        self.assertEqual(combine_cmd[combine_cmd.index("--raw-dir") + 1], str(crawl_root))


if __name__ == "__main__":
    unittest.main()
