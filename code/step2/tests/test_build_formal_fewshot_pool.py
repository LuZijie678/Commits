from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "build_formal_fewshot_pool.py"
SPEC = importlib.util.spec_from_file_location("build_formal_fewshot_pool", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["build_formal_fewshot_pool"] = MOD
SPEC.loader.exec_module(MOD)


M_SOURCE_FIELDNAMES = [
    "repo",
    "sha",
    "commit_url",
    "language",
    "commit_date",
    "subject",
    "commit_message",
    "candidate_layer",
    "m_candidate_score",
    "m_candidate_reasons",
    "llm_label",
    "llm_is_multi_intent",
    "llm_reason",
    "llm_intent_count_estimate",
    "llm_intent_summaries",
    "llm_evidence_from_message",
    "llm_evidence_from_diff",
    "llm_uncertainty",
    "llm_model",
    "llm_created_at_utc",
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
    "file_count",
    "path_roles",
    "top_dirs",
    "changed_files",
    "shortstat",
    "git_diff",
    "diff_status",
    "diff_error",
    "diff_source",
    "diff_char_count_original",
    "diff_truncated",
]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_m_row(repo: str, sha: str, subject: str, *, commit_message: str = "") -> dict[str, str]:
    diff = "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ]
    )
    return {
        "repo": repo,
        "sha": sha,
        "commit_url": f"https://github.com/{repo}/commit/{sha}",
        "language": "Python",
        "commit_date": "2026-05-27",
        "subject": subject,
        "commit_message": commit_message or subject,
        "candidate_layer": "github_api_filelist_only",
        "m_candidate_score": "0.91",
        "m_candidate_reasons": "verified_m",
        "llm_label": "M",
        "llm_is_multi_intent": "True",
        "llm_reason": "two independent intentions",
        "llm_intent_count_estimate": "2",
        "llm_intent_summaries": "fix parser || add tests",
        "llm_evidence_from_message": "message evidence",
        "llm_evidence_from_diff": "diff evidence",
        "llm_uncertainty": "low",
        "llm_model": "test-model",
        "llm_created_at_utc": "2026-05-27T00:00:00Z",
        "_source_file": "fixture.csv",
        "_evidence_mode": "real_diff",
        "_needs_diff_verify": "0",
        "file_count": "2",
        "path_roles": "src,test",
        "top_dirs": "src,test",
        "changed_files": "src/app.py;tests/test_app.py",
        "shortstat": "2 files changed",
        "git_diff": diff,
        "diff_status": "ok",
        "diff_error": "",
        "diff_source": "fixture",
        "diff_char_count_original": str(len(diff)),
        "diff_truncated": "0",
    }


def make_review_row(repo: str, sha: str, sig: str, subject_original: str, subject_normalized: str, *, needs_norm: int = 0) -> dict[str, str]:
    return {
        "review_decision": "accept",
        "verified_multi_intent": "1",
        "type_signature_canonical": sig,
        "type_signature_raw": sig,
        "intent_k": "2",
        "subject_normalized": subject_normalized,
        "fewshot_eligible": "1",
        "quality_status": "pass",
        "quality_score": "0.95",
        "message_status": "pass",
        "reviewer": "tester",
        "review_round": "round1",
        "review_notes": "verified",
        "subject_original": subject_original,
        "subject_normalized_suggested": subject_normalized,
        "intent_k_suggested": "2",
        "needs_subject_normalization": str(needs_norm),
        "style_clean": "1",
        "style_reasons": "[]",
        "strict_repo_sha_disjoint": "1",
        "sha_overlaps_step2_source": "0",
        "repo_overlaps_step2_source": "0",
        "repo": repo,
        "sha": sha,
        "commit_url": f"https://github.com/{repo}/commit/{sha}",
        "subject": subject_original,
        "commit_message": subject_original,
        "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
        "language": "Python",
        "commit_date": "2026-05-27",
        "file_count": "2",
        "path_roles": "src,test",
        "top_dirs": "src,test",
        "changed_files": "src/app.py;tests/test_app.py",
        "shortstat": "2 files changed",
        "candidate_layer": "github_api_filelist_only",
        "m_candidate_score": "0.91",
        "m_candidate_reasons": "verified_m",
        "llm_label": "M",
        "llm_is_multi_intent": "True",
        "llm_reason": "two independent intentions",
        "llm_intent_count_estimate": "2",
        "llm_intent_summaries": "fix parser || add tests",
        "llm_evidence_from_message": "message evidence",
        "llm_evidence_from_diff": "diff evidence",
        "llm_uncertainty": "low",
        "llm_model": "test-model",
        "llm_created_at_utc": "2026-05-27T00:00:00Z",
        "_source_file": "fixture.csv",
        "_evidence_mode": "real_diff",
        "_needs_diff_verify": "0",
        "diff_status": "ok",
        "diff_error": "",
        "diff_source": "fixture",
        "diff_char_count_original": "64",
        "diff_truncated": "0",
    }


def test_prepare_candidates_generates_disjoint_review_sheet(tmp_path: Path) -> None:
    input_csv = tmp_path / "usable_m.csv"
    step2_source_csv = tmp_path / "step2_source.csv"
    candidate_csv = tmp_path / "candidate.csv"
    review_csv = tmp_path / "review.csv"
    report_json = tmp_path / "candidate_report.json"
    report_md = tmp_path / "candidate_report.md"

    write_csv(
        input_csv,
        M_SOURCE_FIELDNAMES,
        [
            make_m_row("owner/repo1", "sha1", "fix parser fallback and add tests"),
            make_m_row("owner/repo2", "sha2", "fix: parser cleanup; docs: update guide"),
        ],
    )
    write_csv(step2_source_csv, ["repo", "sha"], [{"repo": "owner/repo1", "sha": "other"}])

    args = SimpleNamespace(
        input_csv=input_csv,
        step2_source_csv=step2_source_csv,
        candidate_csv=candidate_csv,
        review_sheet_csv=review_csv,
        report_json=report_json,
        report_md=report_md,
    )
    MOD.prepare_candidates(args)

    candidate_rows = list(csv.DictReader(candidate_csv.open(encoding="utf-8", newline="")))
    review_rows = list(csv.DictReader(review_csv.open(encoding="utf-8", newline="")))
    payload = json.loads(report_json.read_text(encoding="utf-8"))

    assert len(candidate_rows) == 2
    assert len(review_rows) == 1
    assert review_rows[0]["repo"] == "owner/repo2"
    assert review_rows[0]["review_decision"] == "pending"
    assert candidate_rows[0]["repo_overlaps_step2_source"] == "1"
    assert candidate_rows[1]["strict_repo_sha_disjoint"] == "1"
    assert payload["stats"]["strict_repo_sha_disjoint_rows"] == 1
    assert payload["stats"]["style_bad_rows"] == 1
    assert "mechanical_semicolon" in payload["stats"]["style_reason_counts"]


def test_report_review_sheet_returns_blockers_for_invalid_accept(tmp_path: Path) -> None:
    review_csv = tmp_path / "review.csv"
    output_json = tmp_path / "summary.json"
    output_md = tmp_path / "summary.md"
    rows = [
        {
            **make_review_row("owner/repo1", "sha1", "fix+test", "orig one", "clean normalized subject"),
            "quality_status": "",
        },
        {
            **make_review_row("owner/repo2", "sha2", "feat+docs", "orig two", "another clean subject"),
            "review_decision": "pending",
        },
    ]
    write_csv(review_csv, MOD.default_review_field_order(), rows)

    args = SimpleNamespace(
        review_sheet_csv=review_csv,
        min_final_size=2,
        target_final_size=3,
        max_final_size=4,
        min_per_common_signature=1,
        output_json=output_json,
        output_md=output_md,
    )
    with pytest.raises(SystemExit):
        MOD.report_review_sheet(args)

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert "invalid_accept_rows(count=1)" in payload["blockers"]
    assert any(item.startswith("pending_review_rows") for item in payload["warnings"])
    assert payload["invalid_accept_examples"][0]["repo"] == "owner/repo1"


def test_materialize_fewshot_pool_builds_db_manifest_and_audit(tmp_path: Path) -> None:
    input_csv = tmp_path / "usable_m.csv"
    review_csv = tmp_path / "review.csv"
    delivery_dir = tmp_path / "delivery"
    write_csv(
        input_csv,
        M_SOURCE_FIELDNAMES,
        [make_m_row(f"owner/repo{i}", f"sha{i}", f"subject {i}") for i in range(10)],
    )
    signatures = list(MOD.CONSTRUCT.DEFAULT_FEWSHOT_COMMON_SIGNATURES) + ["fix+test"]
    rows = []
    for index, signature in enumerate(signatures, start=1):
        rows.append(
            make_review_row(
                f"owner/repo{index}",
                f"sha{index}",
                signature,
                f"orig {index}",
                f"clean normalized subject {index}",
                needs_norm=1 if index == 1 else 0,
            )
        )
    write_csv(review_csv, MOD.default_review_field_order(), rows)

    args = SimpleNamespace(
        input_csv=input_csv,
        review_sheet_csv=review_csv,
        delivery_dir=delivery_dir,
        table="fewshot_examples",
        min_final_size=9,
        target_final_size=10,
        max_final_size=10,
        min_per_common_signature=1,
        audit_min_total=1,
        preflight_config=tmp_path / "missing_config.json",
        run_preflight=False,
    )
    MOD.materialize_fewshot_pool(args)

    db_path = delivery_dir / "fewshot_pool.db"
    manifest_path = delivery_dir / "build_manifest.json"
    audit_path = delivery_dir / "fewshot_audit.json"
    summary_path = delivery_dir / "selection_summary.json"
    preflight_path = delivery_dir / "preflight_report.json"
    assert db_path.exists()
    assert manifest_path.exists()
    assert audit_path.exists()
    assert summary_path.exists()
    assert preflight_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT example_id, repo, sha, subject, type_signature_canonical, notes FROM fewshot_examples ORDER BY example_id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 10
    assert rows[0][3].startswith("clean normalized subject")
    assert '"subject_original": "orig' in rows[0][5]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    assert manifest["source_policy"] == "m_only"
    assert manifest["subject_policy"] == "manual_normalized_with_traceability"
    assert manifest["target_size"]["target_final_size"] == 10
    assert manifest["target_size"]["accepted_size_range"] == [9, 10]
    assert audit["passed"] is True
    assert audit["audit"]["audit_pass"] is True
    assert summary["selected_count"] == 10
    assert summary["preflight_attempted"] is False
    assert "step2_preflight_not_passed_or_not_attempted" in summary["warnings"]
    assert preflight["reason"] == "preflight_skipped_by_flag"


def test_materialize_fewshot_pool_blocks_on_missing_common_signature_coverage(tmp_path: Path) -> None:
    input_csv = tmp_path / "usable_m.csv"
    review_csv = tmp_path / "review.csv"
    delivery_dir = tmp_path / "delivery"
    write_csv(
        input_csv,
        M_SOURCE_FIELDNAMES,
        [make_m_row("owner/repo1", "sha1", "subject 1"), make_m_row("owner/repo2", "sha2", "subject 2")],
    )
    write_csv(
        review_csv,
        MOD.default_review_field_order(),
        [
            make_review_row("owner/repo1", "sha1", "fix+test", "orig 1", "clean subject one"),
            make_review_row("owner/repo2", "sha2", "feat+docs", "orig 2", "clean subject two"),
        ],
    )

    args = SimpleNamespace(
        input_csv=input_csv,
        review_sheet_csv=review_csv,
        delivery_dir=delivery_dir,
        table="fewshot_examples",
        min_final_size=2,
        target_final_size=2,
        max_final_size=2,
        min_per_common_signature=1,
        audit_min_total=1,
        preflight_config=tmp_path / "missing_config.json",
        run_preflight=False,
    )
    with pytest.raises(SystemExit):
        MOD.materialize_fewshot_pool(args)

    summary = json.loads((delivery_dir / "selection_summary.json").read_text(encoding="utf-8"))
    assert any(item.startswith("fewshot_common_signature_coverage_insufficient") for item in summary["blockers"])


def test_build_parser_defaults_use_datasets_step2_layout() -> None:
    parser = MOD.build_parser()
    prepare_args = parser.parse_args(["prepare"])
    report_args = parser.parse_args(["report"])
    materialize_args = parser.parse_args(["materialize"])

    assert prepare_args.candidate_csv.as_posix().endswith(
        "datasets/step2/candidate_sources/m_only_disjoint_candidates.csv"
    )
    assert prepare_args.review_sheet_csv.as_posix().endswith(
        "datasets/step2/review/m_only_review_sheet.csv"
    )
    assert report_args.review_sheet_csv.as_posix().endswith(
        "datasets/step2/review/m_only_review_sheet.csv"
    )
    assert materialize_args.delivery_dir.as_posix().endswith(
        "datasets/step2/delivery/current"
    )
