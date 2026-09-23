import importlib.util
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "enrich_candidates_remote_diff.py"


def load_module():
    spec = importlib.util.spec_from_file_location("enrich_candidates_remote_diff", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EnrichCandidatesRemoteDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_enrich_rows_parallel_keeps_input_order(self) -> None:
        rows = [
            {"repo": "owner/slow", "sha": "a1"},
            {"repo": "owner/fast", "sha": "b2"},
            {"repo": "owner/mid", "sha": "c3"},
        ]
        args = SimpleNamespace(
            diff_max_chars=0,
            timeout=10,
            attempts=1,
            max_files=120,
            fetch_max_bytes=1000,
            workers=3,
        )

        def fake_enrich_row(row, diff_max_chars, timeout, attempts, max_files, fetch_max_bytes):
            delays = {"owner/slow": 0.08, "owner/fast": 0.01, "owner/mid": 0.03}
            time.sleep(delays[row["repo"]])
            return {"repo": row["repo"], "sha": row["sha"], "diff_status": "ok", "git_diff": "diff --git "}

        with patch.object(self.module, "enrich_row", side_effect=fake_enrich_row):
            enriched, skipped = self.module.enrich_rows(rows, args, set())

        self.assertEqual(skipped, 0)
        self.assertEqual([(row["repo"], row["sha"]) for row in enriched], [(row["repo"], row["sha"]) for row in rows])

    def test_enrich_rows_respects_existing_output_keys(self) -> None:
        rows = [
            {"repo": "owner/skip", "sha": "a1"},
            {"repo": "owner/keep", "sha": "b2"},
        ]
        args = SimpleNamespace(
            diff_max_chars=0,
            timeout=10,
            attempts=1,
            max_files=120,
            fetch_max_bytes=1000,
            workers=2,
        )

        with patch.object(
            self.module,
            "enrich_row",
            return_value={"repo": "owner/keep", "sha": "b2", "diff_status": "ok", "git_diff": "diff --git "},
        ) as enrich_row:
            enriched, skipped = self.module.enrich_rows(rows, args, {("owner/skip", "a1")})

        self.assertEqual(skipped, 0)
        self.assertEqual(enrich_row.call_count, 1)
        self.assertEqual([(row["repo"], row["sha"]) for row in enriched], [("owner/keep", "b2")])


if __name__ == "__main__":
    unittest.main()
