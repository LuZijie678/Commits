from __future__ import annotations

from code.mica.eval.message_utility import check_message_supported_by_evidence, compute_unsupported_claim_flags


def test_check_message_supported_by_evidence_flags_unsupported_security_claim() -> None:
    plan = {"intents": [{"subject": "update auth flow"}], "metadata": {}, "evidence_terms": ["auth", "token"]}

    supported = check_message_supported_by_evidence("improve auth token security", plan)
    flags = compute_unsupported_claim_flags("improve auth token security", plan)

    assert supported["supported_by_evidence"] is False
    assert flags["unsupported_claims"]["security"] is True
