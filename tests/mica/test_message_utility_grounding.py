from __future__ import annotations

from code.mica.eval.message_utility import compute_entity_copy_rate, extract_evidence_terms


def test_extract_evidence_terms_and_entity_copy_rate() -> None:
    plan = {
        "intents": [
            {
                "subject": "update auth token flow",
                "evidence_units": [
                    {"file_path": "src/auth.py", "changed_identifiers": ["auth", "token"], "file_role": "source"}
                ],
            }
        ]
    }

    terms = extract_evidence_terms(plan)
    rate = compute_entity_copy_rate("update auth token flow", terms)

    assert "auth" in terms
    assert rate["entity_copy_rate"] > 0
