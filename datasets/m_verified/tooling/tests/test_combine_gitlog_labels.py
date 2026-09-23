import argparse
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "combine_gitlog_labels.py"


def load_module():
    spec = importlib.util.spec_from_file_location("combine_gitlog_labels", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class CombineGitlogLabelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_combine_preserves_existing_combined_rows_and_overlays_new_labels(self) -> None:
        fields = self.module.OUTPUT_FIELDS
        old_one = {
            "repo": "owner/repo1",
            "sha": "aaa",
            "llm_label": "A",
            "_evidence_mode": "diff_or_diff_preferred",
        }
        old_two = {
            "repo": "owner/repo2",
            "sha": "bbb",
            "llm_label": "B",
            "_evidence_mode": "diff_or_diff_preferred",
        }
        new_two = {
            "repo": "owner/repo2",
            "sha": "bbb",
            "llm_label": "M",
            "_evidence_mode": "diff_or_diff_preferred",
        }
        new_three = {
            "repo": "owner/repo3",
            "sha": "ccc",
            "llm_label": "B",
            "_evidence_mode": "diff_or_diff_preferred",
        }
        existing_rows = [{field: row.get(field, "") for field in fields} for row in [old_one, old_two]]
        new_rows = [{field: row.get(field, "") for field in fields} for row in [new_two, new_three]]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels_dir = root / "labels"
            raw_dir = root / "raw"
            output_combined = labels_dir / "gitlog_all_pilot_labels_combined.csv"
            output_m = labels_dir / "gitlog_current_m_candidates.csv"
            summary = labels_dir / "summary.json"
            new_label_csv = labels_dir / "batch_labeled.csv"

            write_rows(output_combined, fields, existing_rows)
            write_rows(new_label_csv, fields, new_rows)

            args = argparse.Namespace(
                labels_dir=labels_dir,
                raw_dir=raw_dir,
                output_combined=output_combined,
                output_m=output_m,
                summary=summary,
                seed_label_csv=[],
            )

            combined, m_rows, _summary = self.module.combine(args)

        by_key = {(row["repo"], row["sha"]): row for row in combined}
        self.assertEqual(len(combined), 3)
        self.assertEqual(by_key[("owner/repo1", "aaa")]["llm_label"], "A")
        self.assertEqual(by_key[("owner/repo2", "bbb")]["llm_label"], "M")
        self.assertEqual(by_key[("owner/repo3", "ccc")]["llm_label"], "B")
        self.assertEqual([(row["repo"], row["sha"]) for row in m_rows], [("owner/repo2", "bbb")])

    def test_combine_accepts_explicit_seed_file_without_csv_suffix(self) -> None:
        fields = self.module.OUTPUT_FIELDS
        seed_row = {
            "repo": "owner/repo1",
            "sha": "aaa",
            "llm_label": "B",
            "_evidence_mode": "diff_or_diff_preferred",
        }
        new_row = {
            "repo": "owner/repo2",
            "sha": "bbb",
            "llm_label": "M",
            "_evidence_mode": "diff_or_diff_preferred",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels_dir = root / "labels"
            raw_dir = root / "raw"
            output_combined = labels_dir / "gitlog_all_pilot_labels_combined.csv"
            output_m = labels_dir / "gitlog_current_m_candidates.csv"
            summary = labels_dir / "summary.json"
            seed_file = root / "seed_object"
            new_label_csv = labels_dir / "batch_labeled.csv"

            write_rows(seed_file, fields, [{field: seed_row.get(field, "") for field in fields}])
            write_rows(new_label_csv, fields, [{field: new_row.get(field, "") for field in fields}])

            args = argparse.Namespace(
                labels_dir=labels_dir,
                raw_dir=raw_dir,
                output_combined=output_combined,
                output_m=output_m,
                summary=summary,
                seed_label_csv=[seed_file],
            )

            combined, m_rows, _summary = self.module.combine(args)

        self.assertEqual(len(combined), 2)
        self.assertEqual({(row["repo"], row["sha"]) for row in combined}, {("owner/repo1", "aaa"), ("owner/repo2", "bbb")})
        self.assertEqual([(row["repo"], row["sha"]) for row in m_rows], [("owner/repo2", "bbb")])


if __name__ == "__main__":
    unittest.main()
