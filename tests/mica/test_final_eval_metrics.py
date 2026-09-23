from __future__ import annotations

from code.mica.reporting import (
    build_alignment_main_table,
    build_message_utility_table,
    build_real_domain_main_table,
)


def test_main_table_builders_return_structured_rows() -> None:
    real_domain = build_real_domain_main_table([{"model": "mica", "auroc": 0.8}])
    alignment = build_alignment_main_table([{"model": "mica", "pairwise_f1": 0.7}])
    message = build_message_utility_table([{"model": "mica", "intent_coverage": 0.6}])

    assert real_domain["table_name"] == "real_domain_main"
    assert alignment["table_name"] == "alignment_main"
    assert message["table_name"] == "message_utility_main"
    assert len(real_domain["rows"]) == 1
