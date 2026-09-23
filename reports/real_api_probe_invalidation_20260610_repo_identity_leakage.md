# Real API Probe Invalidation

- invalidated: `True`
- invalidated_probe_root: `outputs/llm_generation_real_api_probe_20260610T082307Z`
- invalidated_probe_result: `reports/real_api_probe_result_20260610T083753Z.json`
- reason: `canonical_repo_identity_leakage`
- affected_sample_id: `M_real_multi:7da239a00c1c6f17`
- query_repo_original: `ArthurSonzogni/FTXUI`
- retrieved_repo_original: `arthursonzogni/ftxui`
- query_repo_canonical: `arthursonzogni/ftxui`
- retrieved_repo_canonical: `arthursonzogni/ftxui`
- same_repo_canonical: `True`
- recommend_65_request_canary: `False`

The invalidated probe may still be used for debugging and qualitative inspection, but not as the formal gate into the 65-request Canary.
