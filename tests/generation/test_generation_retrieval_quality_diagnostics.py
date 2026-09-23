import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from retrieve_generation_exemplars import retrieve_for_sample


def test_retrieval_quality_marks_low_similarity_warning():
    sample = {
        "sample_id": "synthetic_multi:s1",
        "repo": "example/repo",
        "repo_canonical": "example/repo",
        "source_shas": ["sha1"],
        "sha": "sha1",
        "data_category": "synthetic_multi",
        "subject_reference": "fix doc paths and tests",
        "diff_text": "doc paths and tests",
    }
    pool = [
        {"exemplar_id": "e1", "repo": "r1", "sha": "b", "type_signature": "", "embedding_text": "doc paths", "diff_fingerprint": "fp1", "normalized_subject": "n1", "subject": "doc paths"},
        {"exemplar_id": "e2", "repo": "r2", "sha": "c", "type_signature": "", "embedding_text": "completely unrelated", "diff_fingerprint": "fp2", "normalized_subject": "n2", "subject": "unrelated"},
        {"exemplar_id": "e3", "repo": "r3", "sha": "d", "type_signature": "", "embedding_text": "also unrelated content", "diff_fingerprint": "fp3", "normalized_subject": "n3", "subject": "unrelated 2"},
    ]
    _, log = retrieve_for_sample(sample, pool, strategy="retrieval", k=3, seed=1, low_similarity_threshold=0.10)
    assert log["returned_k"] == 3
    assert log["low_similarity_warning"] is True
    assert log["low_similarity_count"] >= 1
    assert log["retrieval_quality_status"] == "usable_with_diagnostics"
    assert log["similarity_top1"] >= log["similarity_min"]


def test_retrieval_quality_marks_insufficient_exemplars():
    sample = {
        "sample_id": "synthetic_multi:s2",
        "repo": "example/repo",
        "repo_canonical": "example/repo",
        "source_shas": ["sha1"],
        "sha": "sha1",
        "data_category": "synthetic_multi",
        "subject_reference": "fix doc paths and tests",
        "diff_text": "doc paths and tests",
    }
    pool = [
        {"exemplar_id": "e1", "repo": "r1", "sha": "b", "type_signature": "", "embedding_text": "unrelated one", "diff_fingerprint": "fp1", "normalized_subject": "n1", "subject": "x"},
    ]
    _, log = retrieve_for_sample(sample, pool, strategy="retrieval", k=3, seed=1, low_similarity_threshold=0.10)
    assert log["returned_k"] == 1
    assert log["retrieval_quality_status"] == "insufficient_exemplars"


def test_retrieval_quality_marks_all_low_similarity():
    sample = {
        "sample_id": "synthetic_multi:s3",
        "repo": "example/repo",
        "repo_canonical": "example/repo",
        "source_shas": ["sha1"],
        "sha": "sha1",
        "data_category": "synthetic_multi",
        "subject_reference": "fix doc paths and tests",
        "diff_text": "doc paths and tests",
    }
    pool = [
        {"exemplar_id": "e1", "repo": "r1", "sha": "b", "type_signature": "", "embedding_text": "alpha beta gamma", "diff_fingerprint": "fp1", "normalized_subject": "n1", "subject": "x"},
        {"exemplar_id": "e2", "repo": "r2", "sha": "c", "type_signature": "", "embedding_text": "delta epsilon zeta", "diff_fingerprint": "fp2", "normalized_subject": "n2", "subject": "y"},
    ]
    _, log = retrieve_for_sample(sample, pool, strategy="retrieval", k=2, seed=1, low_similarity_threshold=0.10)
    assert log["retrieval_quality_status"] == "all_low_similarity"
    assert log["low_similarity_warning"] is True
