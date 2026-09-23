import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from report_real_api_probe_invalidation import write_repo_identity_invalidation_report


def test_invalidation_report_marks_repo_identity_leakage(tmp_path):
    output_root = tmp_path / "probe"
    reports_root = tmp_path / "reports"
    (output_root / "dataset").mkdir(parents=True)
    (output_root / "retrieval_logs").mkdir(parents=True)
    (output_root / "exemplar_pool").mkdir(parents=True)
    (output_root / "dataset" / "canary_all.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "M_real_multi:7da239a00c1c6f17",
                "repo": "ArthurSonzogni/FTXUI",
                "sha": "query_sha",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_root / "retrieval_logs" / "retrieval_logs.jsonl").write_text(
        json.dumps(
            {
                "query_sample_id": "M_real_multi:7da239a00c1c6f17",
                "generation_strategy": "G4",
                "retrieved_exemplar_ids": ["ex:ftxui"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_root / "exemplar_pool" / "exemplar_pool.jsonl").write_text(
        json.dumps(
            {
                "exemplar_id": "ex:ftxui",
                "repo": "arthursonzogni/ftxui",
                "sha": "ex_sha",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    probe_result_json = reports_root / "probe_result.json"
    reports_root.mkdir(parents=True)
    probe_result_json.write_text("{}\n", encoding="utf-8")
    report = write_repo_identity_invalidation_report(
        output_root=output_root,
        probe_result_json=probe_result_json,
        reports_root=reports_root,
        report_prefix="invalidation_fixture",
    )
    assert report["invalidated"] is True
    assert report["reason"] == "canonical_repo_identity_leakage"
    assert report["same_repo_canonical"] is True
    assert report["query_repo_canonical"] == "arthursonzogni/ftxui"
    assert report["retrieved_repo_canonical"] == "arthursonzogni/ftxui"
    assert report["recommend_65_request_canary"] is False
