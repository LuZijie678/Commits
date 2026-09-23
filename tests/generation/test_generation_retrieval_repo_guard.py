import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from retrieve_generation_exemplars import retrieve_for_sample


def _sample() -> dict:
    return {
        "sample_id": "M_real_multi:ftxui",
        "repo": "ArthurSonzogni/FTXUI",
        "repo_canonical": "arthursonzogni/ftxui",
        "source_shas": ["query_sha"],
        "sha": "query_sha",
        "data_category": "M_real_multi",
        "subject_reference": "Improve ABI stability and optimize rendering performance",
        "normalized_subject": "improve abi stability and optimize rendering performance",
        "diff_text": "flatten surface cells and refactor component base",
        "diff_fingerprint": "fp-query",
    }


def _pool() -> list[dict]:
    return [
        {
            "exemplar_id": "bad-case",
            "repo": "arthursonzogni/ftxui",
            "sha": "case_sha",
            "type_signature": "M_real_multi|files=0|exts=",
            "embedding_text": "flatten surface cells",
            "diff_fingerprint": "fp-case",
            "normalized_subject": "different subject",
            "subject": "same repo lowercase",
        },
        {
            "exemplar_id": "bad-url",
            "repo": "https://github.com/ArthurSonzogni/FTXUI.git",
            "sha": "url_sha",
            "type_signature": "M_real_multi|files=0|exts=",
            "embedding_text": "component base internals",
            "diff_fingerprint": "fp-url",
            "normalized_subject": "another subject",
            "subject": "same repo url",
        },
        {
            "exemplar_id": "bad-subject",
            "repo": "other/repo",
            "sha": "subject_sha",
            "type_signature": "M_real_multi|files=0|exts=",
            "embedding_text": "other retrieval text",
            "diff_fingerprint": "fp-subject",
            "normalized_subject": "improve abi stability and optimize rendering performance",
            "subject": "same subject",
        },
        {
            "exemplar_id": "bad-fingerprint",
            "repo": "other/repo2",
            "sha": "fp_sha",
            "type_signature": "M_real_multi|files=0|exts=",
            "embedding_text": "other retrieval text 2",
            "diff_fingerprint": "fp-query",
            "normalized_subject": "distinct subject",
            "subject": "same fingerprint",
        },
        {
            "exemplar_id": "bad-source-sha",
            "repo": "other/repo3",
            "sha": "query_sha",
            "type_signature": "M_real_multi|files=0|exts=",
            "embedding_text": "other retrieval text 3",
            "diff_fingerprint": "fp-source",
            "normalized_subject": "distinct subject 2",
            "subject": "same sha",
        },
        {
            "exemplar_id": "ok",
            "repo": "friendlyanon/cmake-init",
            "sha": "ok_sha",
            "type_signature": "M_real_multi|files=0|exts=",
            "embedding_text": "flatten surface cells for renderer",
            "diff_fingerprint": "fp-ok",
            "normalized_subject": "distinct subject 3",
            "subject": "good exemplar",
        },
    ]


def test_retrieval_repo_guard_excludes_same_repo_case_and_url_variants():
    chosen, log = retrieve_for_sample(_sample(), _pool(), strategy="retrieval", k=3, seed=1)
    assert [row["exemplar_id"] for row in chosen] == ["ok"]
    assert log["same_repo_original_string"] is False
    assert log["same_repo_canonical"] is False
    assert log["repo_guard_exclusion_count"] == 2
    excluded_ids = {row["candidate_id"] for row in log["repo_guard_excluded_candidates"]}
    assert excluded_ids == {"bad-case", "bad-url"}
    assert log["query_repo_canonical"] == "arthursonzogni/ftxui"
    assert log["retrieved_repo_canonical"] == ["friendlyanon/cmake-init"]
    assert log["filter_reasons"]["same_repo_canonical"] == 2
    assert log["filter_reasons"]["source_sha_overlap"] == 1
    assert log["filter_reasons"]["diff_fingerprint_overlap"] == 1
    assert log["filter_reasons"]["normalized_subject_overlap"] == 1


def test_random_and_type_matched_also_use_canonical_repo_guard():
    for strategy in ["random", "type_matched"]:
        chosen, log = retrieve_for_sample(_sample(), _pool(), strategy=strategy, k=3, seed=2)
        assert all(row["repo_canonical"] != "arthursonzogni/ftxui" for row in chosen)
        assert log["same_repo_canonical"] is False
        assert log["repo_guard_exclusion_count"] == 2
