import csv
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "filter_step1_candidates_against_step2.py"


class Step2LeakageFilterTest(unittest.TestCase):
    def write_csv(self, path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_filters_sha_overlap_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            input_csv = base / "prefilter_allcommits.csv"
            step2_csv = base / "step2_source.csv"
            output_csv = base / "filtered.csv"
            report_json = base / "report.json"

            self.write_csv(
                input_csv,
                ["repo", "sha", "type", "message"],
                [
                    {"repo": "owner/repo-a", "sha": "keep-1", "type": "fix", "message": "m1"},
                    {"repo": "owner/repo-b", "sha": "drop-sha", "type": "feat", "message": "m2"},
                ],
            )
            self.write_csv(
                step2_csv,
                ["repo", "sha"],
                [
                    {"repo": "another/repo", "sha": "drop-sha"},
                ],
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input-csv",
                    str(input_csv),
                    "--step2-source-csv",
                    str(step2_csv),
                    "--output-csv",
                    str(output_csv),
                    "--report-json",
                    str(report_json),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = list(csv.DictReader(output_csv.open("r", encoding="utf-8", newline="")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sha"], "keep-1")
            report = json.loads(report_json.read_text(encoding="utf-8"))
            self.assertEqual(report["excluded_sha_overlap_count"], 1)
            self.assertEqual(report["excluded_repo_overlap_count"], 0)

    def test_optional_repo_filter_excludes_repo_overlap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            input_csv = base / "prefilter_allcommits.csv"
            step2_csv = base / "step2_source.csv"
            output_csv = base / "filtered.csv"

            self.write_csv(
                input_csv,
                ["repo", "sha", "type", "message"],
                [
                    {"repo": "owner/repo-a", "sha": "keep-1", "type": "fix", "message": "m1"},
                    {"repo": "owner/repo-b", "sha": "keep-sha-but-same-repo", "type": "feat", "message": "m2"},
                ],
            )
            self.write_csv(
                step2_csv,
                ["repo", "sha"],
                [
                    {"repo": "owner/repo-b", "sha": "other-sha"},
                ],
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input-csv",
                    str(input_csv),
                    "--step2-source-csv",
                    str(step2_csv),
                    "--output-csv",
                    str(output_csv),
                    "--exclude-repo-overlap",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = list(csv.DictReader(output_csv.open("r", encoding="utf-8", newline="")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sha"], "keep-1")

    def test_additional_exclusion_csv_can_remove_annotated_repo_overlap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            input_csv = base / "prefilter_allcommits.csv"
            step2_csv = base / "step2_source.csv"
            annotated_csv = base / "annotated.csv"
            output_csv = base / "filtered.csv"
            report_json = base / "report.json"

            self.write_csv(
                input_csv,
                ["repo", "sha", "type", "message"],
                [
                    {"repo": "owner/repo-a", "sha": "keep-1", "type": "fix", "message": "m1"},
                    {"repo": "owner/repo-b", "sha": "drop-by-annotated-repo", "type": "feat", "message": "m2"},
                ],
            )
            self.write_csv(
                step2_csv,
                ["repo", "sha"],
                [
                    {"repo": "another/repo", "sha": "other-sha"},
                ],
            )
            self.write_csv(
                annotated_csv,
                ["repo", "sha"],
                [
                    {"repo": "owner/repo-b", "sha": "annotated-sha"},
                ],
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input-csv",
                    str(input_csv),
                    "--step2-source-csv",
                    str(step2_csv),
                    "--additional-exclusion-csv",
                    str(annotated_csv),
                    "--output-csv",
                    str(output_csv),
                    "--report-json",
                    str(report_json),
                    "--exclude-repo-overlap",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = list(csv.DictReader(output_csv.open("r", encoding="utf-8", newline="")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sha"], "keep-1")
            report = json.loads(report_json.read_text(encoding="utf-8"))
            self.assertEqual(report["additional_exclusion_csv_count"], 1)
            self.assertEqual(report["excluded_repo_overlap_count"], 1)


if __name__ == "__main__":
    unittest.main()
