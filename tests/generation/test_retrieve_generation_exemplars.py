import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from retrieve_generation_exemplars import retrieve_for_sample


def test_retrieval_strategies_are_reproducible():
    sample = {"sample_id": "s1", "repo": "r0", "repo_canonical": "r0", "source_shas": ["a"], "data_category": "hard_b", "diff_text": "add parser support"}
    pool = [
        {"exemplar_id": "e1", "repo": "r1", "sha": "b", "type_signature": "hard_b|files=0|exts=", "embedding_text": "add parser support"},
        {"exemplar_id": "e2", "repo": "r2", "sha": "c", "type_signature": "hard_b|files=0|exts=", "embedding_text": "update docs"},
        {"exemplar_id": "e3", "repo": "r3", "sha": "d", "type_signature": "hard_b|files=0|exts=", "embedding_text": "fix parser"},
    ]
    first, log1 = retrieve_for_sample(sample, pool, strategy="retrieval", k=2, seed=42)
    second, log2 = retrieve_for_sample(sample, pool, strategy="retrieval", k=2, seed=42)
    assert [x["exemplar_id"] for x in first] == [x["exemplar_id"] for x in second]
    assert log1["retrieved_exemplar_ids"] == log2["retrieved_exemplar_ids"]


def test_retrieval_filters_same_repo():
    sample = {"sample_id": "s1", "repo": "r0", "repo_canonical": "r0", "source_shas": ["a"], "data_category": "hard_b", "diff_text": "add parser support"}
    pool = [
        {"exemplar_id": "bad", "repo": "r0", "sha": "x", "type_signature": "", "embedding_text": "add parser support"},
        {"exemplar_id": "ok", "repo": "r1", "sha": "b", "type_signature": "", "embedding_text": "add parser support"},
    ]
    chosen, log = retrieve_for_sample(sample, pool, strategy="retrieval", k=2, seed=1)
    assert [x["exemplar_id"] for x in chosen] == ["ok"]
    assert log["filter_reasons"]["same_repo_canonical"] == 1
    assert log["repo_guard_exclusion_count"] == 1
