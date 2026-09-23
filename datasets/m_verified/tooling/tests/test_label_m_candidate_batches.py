import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "label_m_candidate_batches.py"


def load_module():
    spec = importlib.util.spec_from_file_location("label_m_candidate_batches", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LabelMCandidateBatchesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_parse_label_response_accepts_json_fenced_block(self) -> None:
        raw = """Here is the result:

```json
{"label":"M","reason":"two independent intents","uncertainty":"low","intent_count_estimate":2,"intent_summaries":["fix bug","add feature"]}
```
"""
        parsed = self.module.parse_label_response(raw)
        self.assertEqual(parsed["label"], "M")
        self.assertEqual(parsed["intent_count_estimate"], 2)

    def test_build_labeled_row_preserves_source_fields(self) -> None:
        source_row = {
            "repo": "owner/repo",
            "sha": "abc123",
            "commit_url": "https://example.test/c/abc123",
            "language": "Python",
            "commit_date": "2026-05-27T00:00:00Z",
            "subject": "fix parser and add metrics",
            "commit_message": "fix parser and add metrics",
            "candidate_layer": "candidate_csv_remote_diff_enriched",
            "m_candidate_score": "42.0",
            "m_candidate_reasons": "subject_and_links_actions",
            "shortstat": "2 files changed",
            "changed_files": "src/a.py\nsrc/b.py",
            "evidence_mode": "diff",
            "diff_status": "ok",
            "git_diff": "diff --git a/src/a.py b/src/a.py",
        }
        label_result = {
            "label": "M",
            "reason": "The commit combines a bug fix and a feature addition.",
            "uncertainty": "low",
            "intent_count_estimate": 2,
            "intent_summaries": ["fix parser", "add metrics"],
        }

        row = self.module.build_labeled_row(
            source_row,
            label_result,
            model_name="test-model",
            created_at_utc="2026-05-27T01:00:00Z",
            source_file="/tmp/out.csv",
        )

        self.assertEqual(row["repo"], "owner/repo")
        self.assertEqual(row["sha"], "abc123")
        self.assertEqual(row["llm_label"], "M")
        self.assertEqual(row["_evidence_mode"], "diff")
        self.assertEqual(row["_needs_diff_verify"], "0")

    def test_ensure_api_key_reads_fixed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".llm_api_key"
            key_file.write_text("secret-token\n", encoding="utf-8")
            args = self.module.argparse.Namespace(api_key_file=key_file)
            self.assertEqual(self.module.ensure_api_key(args), "secret-token")

    def test_parse_args_defaults_api_key_file(self) -> None:
        argv = sys.argv[:]
        try:
            sys.argv = [
                "label_m_candidate_batches.py",
                "--input-csv",
                "/tmp/in.csv",
                "--output-csv",
                "/tmp/out.csv",
                "--output-jsonl",
                "/tmp/out.jsonl",
                "--summary",
                "/tmp/summary.json",
            ]
            args = self.module.parse_args()
        finally:
            sys.argv = argv
        self.assertEqual(args.api_key_file.name, ".llm_api_key")


if __name__ == "__main__":
    unittest.main()
