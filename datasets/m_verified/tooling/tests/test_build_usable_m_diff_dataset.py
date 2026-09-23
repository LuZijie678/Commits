import http.client
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_usable_m_diff_dataset.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_usable_m_diff_dataset", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildUsableMDiffDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_remote_diff_recover_uses_incomplete_read_partial_when_real_diff_present(self) -> None:
        partial = b"diff --git a/a b/a\n+hello\n"
        exc = http.client.IncompleteRead(partial, 10)

        with patch.object(self.module.urllib.request, "urlopen", side_effect=exc):
            result = self.module.remote_diff_recover(
                {"repo": "owner/repo", "sha": "abc123"},
                timeout=5,
                attempts=1,
            )

        self.assertEqual(result["ok"], "1")
        self.assertIn("diff --git ", result["git_diff"])
        self.assertIn("IncompleteRead_partial_used", result["diff_error"])

    def test_discover_evidence_files_includes_existing_output_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            labels_dir = base / "labels"
            raw_dir = base / "raw"
            output_csv = base / "datasets" / "usable_m_with_real_diff.csv"
            labels_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)
            output_csv.parent.mkdir(parents=True, exist_ok=True)
            output_csv.write_text("repo,sha,git_diff\nowner/repo,abc,diff --git a/a b/a\n", encoding="utf-8")

            files = self.module.discover_evidence_files(labels_dir, raw_dir, output_csv)

        self.assertIn(output_csv, files)

    def test_discover_evidence_files_includes_explicit_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            labels_dir = base / "labels"
            raw_dir = base / "raw"
            extra_csv = base / "crawl_state_relaxed" / "round0084_remote_diff.csv"
            labels_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)
            extra_csv.parent.mkdir(parents=True, exist_ok=True)
            extra_csv.write_text("repo,sha,git_diff\nowner/repo,abc,diff --git a/a b/a\n", encoding="utf-8")

            files = self.module.discover_evidence_files(labels_dir, raw_dir, None, [extra_csv])

        self.assertIn(extra_csv, files)


if __name__ == "__main__":
    unittest.main()
